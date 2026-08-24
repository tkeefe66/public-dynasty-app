"""Yahoo's XML-shaped JSON -> plain dicts and lists.

Yahoo's ``format=json`` output is its XML transliterated, which produces two
encodings nothing else in this codebase has to deal with:

1. **Numeric-key collections.** A list of N things is an object with keys
   "0".."N-1" plus a "count". Ordering must be numeric — "10" sorts before "2"
   as a string, which would silently reorder a 12-team league.
2. **Fragmented resources.** One logical resource arrives as a *list* of
   partial dicts (and sometimes nested lists) that have to be merged to see
   the whole thing.

Isolated here and unit-tested so the adapter's own modules read as ordinary
mapping code. Both encodings are corroborated by an independent Yahoo client
(derekrbreese/fantasy-football-mcp-public, MIT) whose parsers hit the same
shapes — but that project never reads transactions, draft results, or the
scoreboard's playoff flags, so those remain fixture-verified rather than
assumed.
"""

from __future__ import annotations


def collection(node) -> list:
    """A Yahoo collection -> a plain list, in numeric key order.

    Accepts the ``{"0": …, "1": …, "count": N}`` encoding, a plain list, or
    None/empty (-> []).
    """
    if node is None:
        return []
    if isinstance(node, list):
        return node
    if not isinstance(node, dict):
        return []
    keys = [k for k in node if str(k).isdigit()]
    return [node[k] for k in sorted(keys, key=int)]


def merge_fragments(node) -> dict:
    """A fragmented Yahoo resource -> one flat dict.

    A resource can arrive as a list of partial dicts, with nested lists mixed
    in. Merges depth-first, keeping the FIRST value on a key collision:
    Yahoo's leading fragments carry the identifying fields, and letting a
    later fragment overwrite ``team_key`` would corrupt identity.
    """
    if isinstance(node, dict):
        return dict(node)
    if not isinstance(node, list):
        return {}
    out: dict = {}
    for part in node:
        if isinstance(part, dict):
            fragment = part
        elif isinstance(part, list):
            fragment = merge_fragments(part)
        else:
            continue
        for k, v in fragment.items():
            out.setdefault(k, v)
    return out


def unwrap(payload, *path):
    """Walk a key path through nested dicts, returning None if it breaks.

    None rather than raising: a missing sub-resource is normal (a league with
    no trades has no transactions node), and the caller decides whether that
    is empty-and-fine or a real failure.
    """
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node
