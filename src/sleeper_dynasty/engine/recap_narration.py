"""One-take submitted-text envelope shared by script validation and narration."""
MAX_SUBMITTED_CHARACTERS = 6000
MAX_CHUNK_CHARACTERS = 2000
MAX_CHUNKS = 63


def narration_chunks(script):
    segments = ([{'id': 'opening', 'text': script['opening']}] + script['segments']
                + [{'id': 'closing', 'text': script['closing']}])
    chunks = []
    for segment in segments:
        text = segment['text']
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHUNK_CHARACTERS:
            raise ValueError('narration_segment_exceeds_envelope')
        if not chunks or len(chunks[-1]['text']) + 1 + len(text) > MAX_CHUNK_CHARACTERS:
            chunks.append({'text': text, 'segment_ids': [segment['id']]})
        else:
            chunks[-1]['text'] += ' ' + text
            chunks[-1]['segment_ids'].append(segment['id'])
    if len(chunks) > MAX_CHUNKS or sum(len(c['text']) for c in chunks) > MAX_SUBMITTED_CHARACTERS:
        raise ValueError('narration_exceeds_envelope')
    return chunks
