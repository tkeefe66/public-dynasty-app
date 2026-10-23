"""Explicit listening adjudication, separate from immutable recognizer evidence."""
import hashlib
import json
import copy
import re


def review_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def review_speech(script, raw, *, aliases=None, review=None):
    from app.services.recap_video.audio import verify_speech, _tokens, word_text
    original=verify_speech(script,raw,reviewed_aliases=aliases)
    if review is None:
        return {**original,'timeline_transcript':raw}
    if (set(review)!={'version','script_digest','transcript_digest','edits','listening_evidence','approved_issues'}
            or review['version']!='human-listening-v1' or review['script_digest']!=review_digest(script)
            or review['transcript_digest']!=review_digest(raw)
            or not re.fullmatch('[a-f0-9]{64}',review['listening_evidence'])
            or sorted(review['approved_issues'])!=original['issues']
            or set(original['issues'])-{'content_mismatch','speech_confidence_low'}):
        raise ValueError('listening_review_evidence_changed')
    normalized=copy.deepcopy(raw); words=normalized['words']
    ownership=[None]*len(words)
    consumed=0
    for index,segment in enumerate(raw.get('segments',[])):
        matches=[last+1 for last in range(consumed,len(words))
            if words[last]['end']<=segment['end'] and _tokens(word_text(words[consumed:last+1]))==_tokens(segment['text'])]
        if len(matches)!=1: raise ValueError('listening_review_segment_ambiguous')
        end=matches[0];ownership[consumed:end]=[index]*(end-consumed);consumed=end
    edits=review['edits']
    if not isinstance(edits,list) or len(edits)>64: raise ValueError('listening_review_edits_invalid')
    previous=0
    for edit in edits:
        if set(edit)!={'start','end','before','after'}: raise ValueError('listening_review_edit_invalid')
        start,end=edit['start'],edit['end']
        if (type(start)!=int or type(end)!=int or start<previous or not start<end<=len(words)
                or end-start>4 or not isinstance(edit['after'],str)
                or not re.fullmatch(r'[A-Za-z]+(?:[-’\x27][A-Za-z]+)*',edit['after'])
                or word_text(words[start:end]).strip()!=edit['before']
                or len(set(ownership[start:end]))!=1):
            raise ValueError('listening_review_edit_invalid')
        previous=end
    for edit in reversed(edits):
        start,end=edit['start'],edit['end']; group=words[start:end]
        words[start:end]=[{**group[0],'word':(' ' if group[0]['word'].startswith(' ') else '')+edit['after'],
            'end':group[-1]['end'],'probability':min(w['probability'] for w in group)}]
        ownership[start:end]=[ownership[start]]
    normalized['text']=word_text(words)
    for index,segment in enumerate(normalized.get('segments',[])):
        segment['text']=word_text([w for w,owner in zip(words,ownership,strict=True) if owner==index])
    checked=verify_speech(script,normalized,reviewed_aliases=aliases)
    if set(checked['issues'])-{'speech_confidence_low'}:
        raise ValueError('listening_review_content_unresolved')
    # Original confidence is preserved. A named human listening review, not an
    # invented recognizer score, resolves this exact recording's uncertainty.
    return {**checked,'passed':True,'issues':[],'original_issues':original['issues'],
        'verifier_revision':'human-listening-v1','raw_transcript':raw,'timeline_transcript':normalized}
