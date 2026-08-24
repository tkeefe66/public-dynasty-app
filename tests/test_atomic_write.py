import json

import pytest

from sleeper_dynasty.util.atomic import write_json_atomic


def test_writes_and_reads_back(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}


def test_creates_missing_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "nested" / "x.json"
    write_json_atomic(p, [1, 2])
    assert json.loads(p.read_text()) == [1, 2]


def test_existing_file_survives_a_failed_write(tmp_path):
    """The whole point: a write that dies partway must not damage the target.

    json.dump streams, so an unserializable value fails *after* some bytes are
    written — to the temp file, which is discarded. The real file is untouched
    because os.replace never runs."""
    p = tmp_path / "x.json"
    write_json_atomic(p, {"good": 1})
    with pytest.raises(TypeError):
        write_json_atomic(p, {"bad": object()})
    assert json.loads(p.read_text()) == {"good": 1}


def test_leaves_no_temp_files_behind(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})
    with pytest.raises(TypeError):
        write_json_atomic(p, {"bad": object()})
    assert [q.name for q in tmp_path.iterdir()] == ["x.json"]


def test_a_non_finite_float_fails_loud_instead_of_writing_bad_json(tmp_path):
    """C1 backstop (2026-08-17): `json.dump`'s default `allow_nan=True`
    happily writes literal `-Infinity`/`Infinity`/`NaN` -- valid Python
    repr, but not RFC-compliant JSON, so a strict reader (or Starlette's
    own `JSONResponse.render`, which uses `allow_nan=False`) chokes on it
    later, somewhere far from where the bad value was actually produced.
    This is what let a non-finite `draft_needs` margin persist silently
    across refreshes instead of failing the write that introduced it.

    The primary fix lives upstream (`engine/draft_needs.py` no longer
    produces a non-finite margin at all) -- this is the fail-loud backstop
    for the NEXT caller that slips one through, proven the same way
    `test_existing_file_survives_a_failed_write` proves the existing
    TypeError path: the write raises and the prior good file is untouched.

    Falsified: dropping `allow_nan=False` from the `json.dump` call makes
    this test fail with `Failed: DID NOT RAISE` (a `-Infinity` literal
    would be written successfully instead)."""
    p = tmp_path / "x.json"
    write_json_atomic(p, {"good": 1})
    with pytest.raises(ValueError):
        write_json_atomic(p, {"bad": float("-inf")})
    assert json.loads(p.read_text()) == {"good": 1}
    assert [q.name for q in tmp_path.iterdir()] == ["x.json"]


def test_written_file_is_world_readable(tmp_path):
    """mkstemp creates at 0600 and os.replace carries that mode onto the target.
    Without an explicit chmod every store on the cache volume silently narrows
    from 0644 to 0600 the first time it is rewritten."""
    import stat

    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})
    assert stat.S_IMODE(p.stat().st_mode) == 0o644
