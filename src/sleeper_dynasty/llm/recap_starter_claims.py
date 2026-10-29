"""Deterministic checks for numeric starter claims, alongside full editorial review.

This deliberately does not purport to understand arbitrary prose. The input brief
separates roles; these checks catch attributable score/count contradictions even
when a model reviewer approves them.
"""
import re
from decimal import Decimal


def require_starter_claims(text, facts):
    source = facts.to_dict().get('source_snapshot') or {}
    rows = source.get('scores', {}).get(str(source.get('week')), [])
    names = {p['roster_id']: p.get('owner_name') for p in source.get('participants', [])}
    words = dict(zip(('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'), range(11)))
    normalized = text.replace('**', '').replace('__', '').replace('’', "'").lower()
    for paragraph in normalized.split('\n\n'):
        if not re.search(r'\b(?:starters?|lineup|starting)\b', paragraph):
            continue
        owners = [row for row in rows if names.get(row['roster_id']) and re.search(
            r'(?<!\w)' + re.escape(names[row['roster_id']].lower()) + r"(?:'s)?(?!\w)", paragraph)]
        if len(owners) != 1:
            continue  # Ambiguous ownership remains the full reviewer's responsibility.
        row = owners[0]
        started = [Decimal(str(row['players_points'][pid])) for pid in row['starters'] if pid != '0']
        benched = {Decimal(str(value)) for pid, value in row['players_points'].items() if pid not in row['starters']}
        # Bench-only numbers in a starting-lineup paragraph cannot contribute.
        # A mixed-role paragraph needs explicit sentence-local role attribution.
        for sentence in re.split(r'[.!?](?!\d)\s+', paragraph):
            if re.search(r'\bbench(?:ed)?\b', sentence) and not re.search(r'\bstarter|\bstarting\b', sentence):
                continue
            for number in re.findall(r'(?<![\w.])-?\d+\.\d+(?![\w.])', sentence):
                if Decimal(number) in benched and Decimal(number) not in started:
                    raise ValueError(f'Analyst starter claim uses bench score {number}; refusing publication')
        for count, relation, threshold in re.findall(
                r'\b(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten) starters? '
                r'(?:cracked |scored )?(above|over|at least)?\s*(\d+(?:\.\d+)?)\+? points', paragraph):
            expected = int(count) if count.isdigit() else words[count]
            cutoff = Decimal(threshold)
            actual = sum(value > cutoff if relation in ('above', 'over') else value >= cutoff for value in started)
            if actual != expected:
                raise ValueError(f'Analyst starter count {expected} conflicts with verified count {actual}; refusing publication')
