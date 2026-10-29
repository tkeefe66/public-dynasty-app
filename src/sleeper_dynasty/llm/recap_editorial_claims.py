"""Conservative guards for concrete recap claim families, not a prose truth oracle.

Unattributable or broader narrative claims still require independent full review.
Never infer a playoff cutoff from one head-to-head result or a player's score
from the league's highest team total.
"""
import re
from decimal import Decimal


def normalized(text):
    return text.replace('**', '').replace('__', '').replace('’', "'").casefold()


def claim_findings(text, facts, outlook=None):
    packet = facts.to_dict()
    source = packet.get('source_snapshot') or {}
    season = source.get('season', packet.get('season'))
    prose = normalized(text)
    findings = []

    def reject(quote, evidence):
        findings.append({'quote': quote, 'evidence': evidence})

    # Current-season labels and standalone year fragments are not historical
    # comparisons. Explicit historical prose is left to the full reviewer.
    for match in re.finditer(r'\b(?:this (?:is |was )?(?:the )?|in )(20\d{2})(?: season)?(?=[.!]|\b season\b)', prose):
        if re.search(r'\b(?:back|previously)\s+$', prose[:match.start()]):
            continue
        if season is None or int(match[1]) != int(season):
            reject(match[0], f'Current recap season is {season or "unproven"}; correct or remove the year.')

    for paragraph in prose.split('\n\n'):
        for sentence in re.split(r'[.!?](?!\d)\s+', paragraph):
            if (re.search(r'\bif\b', sentence)
                    and re.search(r'\b(?:cutoff|playoff (?:seed|spot|position))\b', sentence)
                    and not re.search(r'\b(?:still |also )?depends? on (?:the )?other games\b', sentence)):
                reject(sentence, 'One head-to-head result does not establish the future playoff cutoff; state only the two teams\' record gap.')
        if re.search(r'\b(?:all|entire)\b[^.!?\n]{0,100}\b(?:contribution|stack)\b', paragraph):
            reject(paragraph, 'An entire NFL-team contribution requires complete membership evidence; name the exact players and their subtotal instead.')
        if re.search(r'\bindividually outscor\w*\b[^.!?\n]{0,80}\b(?:full|entire) rosters?\b', paragraph):
            reject(paragraph, 'Individual-versus-team comparisons need named individual scores and named team totals; do not confuse a combined subtotal with individual scores.')
        if re.search(r'\b(?:projected lineup|(?:optimized[- ]?)?lineup projections?)\b', paragraph) and outlook is None:
            reject(paragraph, 'No saved outlook projection packet supports this projection claim; describe scheduled matchups and record implications only.')
        for matchup in (packet.get('standings_race') or {}).get('upcoming_matchups', []):
            left, right = normalized(matchup['side_a']), normalized(matchup['side_b'])
            if any(re.search(r'(?<!\w)' + re.escape(a) + r'\b[^.!?\n]{0,30}\bhosts\b[^.!?\n]{0,30}\b' + re.escape(b) + r'(?!\w)', paragraph)
                   for a, b in ((left, right), (right, left))):
                reject(paragraph, 'A scheduled fantasy pairing does not establish home-field hosting; use faces or plays.')

    lineups = packet.get('lineups') or []
    players = [p for lineup in lineups for p in lineup.get('starters', [])]
    if not players and re.search(r"\b(?:had|has|rostered) the week's (?:high|highest) scorer\b|tight end and (?:your |his |their )?(?:qb1|quarterback) combine", prose):
        reject('Individual scoring comparison', 'Named individual scoring authority is unavailable; remove the comparison.')
    maximum = max((Decimal(str(p['points'])) for p in players), default=None)
    for lineup in lineups:
        owner = normalized(lineup['owner'])
        for paragraph in prose.split('\n\n'):
            if not re.search(r'(?<!\w)' + re.escape(owner) + r'(?!\w)', paragraph):
                continue
            if re.search(re.escape(owner) + r" (?:had|has|rostered) the week's (?:high|highest) scorer\b", paragraph):
                if maximum is None or not any(Decimal(str(p['points'])) == maximum for p in lineup['starters']):
                    reject(paragraph, 'The highest individual starter belongs to another team; highest team score is a separate distinction.')
            comparison = re.search(r'tight end and (?:your |his |their )?(?:qb1|quarterback) combine(?:d)? for fewer points than ([\w .\'-]+?) had by himself', paragraph)
            if comparison and re.search(r'(?<!\w)' + re.escape(owner) + r'[:,]\s*(?:your |his |their )?$', paragraph[:comparison.start()]):
                positions = [p for p in lineup['starters'] if p.get('position') in ('QB', 'TE')]
                targets = [p for p in players if normalized(p['player'].split(' (')[0]) == comparison[1].strip()]
                if (len(positions) != 2 or len(targets) != 1 or
                        sum(Decimal(str(p['points'])) for p in positions) >= Decimal(str(targets[0]['points']))):
                    reject(comparison[0], 'Recompute the named quarterback plus tight-end subtotal and compare with the named player; this comparison is false or unproven.')
    return findings


def require_editorial_claims(text, facts, outlook=None):
    findings = claim_findings(text, facts, outlook)
    if findings:
        raise ValueError('Analyst editorial claim: ' + '; '.join(f['evidence'] for f in findings) + '; refusing publication')
