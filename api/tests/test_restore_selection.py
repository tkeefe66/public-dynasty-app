import io
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from restore import UnsafeMember, pick_latest_run, safe_extract  # noqa: E402


def test_picks_the_newest_complete_run():
    keys = [
        "backups/2026-08-10T09-00-00Z/manifest.json",
        "backups/2026-08-11T09-00-00Z/manifest.json",
        "backups/2026-08-12T09-00-00Z/manifest.json",
    ]
    assert pick_latest_run(keys) == "2026-08-12T09-00-00Z"


def test_ignores_a_run_with_no_manifest():
    """The manifest is uploaded last, so a prefix without one is a run that
    died partway. Restoring from it would silently restore half a database."""
    keys = [
        "backups/2026-08-11T09-00-00Z/manifest.json",
        "backups/2026-08-12T09-00-00Z/postgres.jsonl.gz",
        "backups/2026-08-12T09-00-00Z/cache.tar.gz",
    ]
    assert pick_latest_run(keys) == "2026-08-11T09-00-00Z"


def test_returns_none_when_nothing_is_complete():
    assert pick_latest_run(["backups/2026-08-12T09-00-00Z/cache.tar.gz"]) is None
    assert pick_latest_run([]) is None


# --- safe_extract -----------------------------------------------------------
#
# A guard only ever shown to accept good input has never been shown to work.
# These build hostile archives by hand — the shapes a real attacker would use if
# they could get a tarball into the bucket.


def _tar_with(tmp_path: Path, build) -> Path:
    path = tmp_path / "hostile.tar"
    with tarfile.open(path, "w") as tar:
        build(tar)
    return path


def _add_file(tar: tarfile.TarFile, name: str, body: bytes = b"pwned") -> None:
    info = tarfile.TarInfo(name)
    info.size = len(body)
    tar.addfile(info, io.BytesIO(body))


def test_extracts_a_normal_archive(tmp_path):
    src = _tar_with(tmp_path, lambda t: _add_file(t, "snapshots/2026-08-01.json", b"{}"))
    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(src) as tar:
        assert safe_extract(tar, dest) == 1
    assert (dest / "snapshots/2026-08-01.json").read_bytes() == b"{}"


def test_refuses_a_member_that_climbs_out_of_the_destination(tmp_path):
    src = _tar_with(tmp_path, lambda t: _add_file(t, "../escape.json"))
    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(src) as tar:
        with pytest.raises(UnsafeMember):
            safe_extract(tar, dest)
    assert not (tmp_path / "escape.json").exists()
    assert list(dest.iterdir()) == []


def test_refuses_an_absolute_member(tmp_path):
    outside = tmp_path / "abs.json"
    src = _tar_with(tmp_path, lambda t: _add_file(t, str(outside)))
    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(src) as tar:
        with pytest.raises(UnsafeMember):
            safe_extract(tar, dest)
    assert not outside.exists()
    assert list(dest.iterdir()) == []


def test_refuses_a_symlink_member(tmp_path):
    """The hole the old code had: members were vetted, then extractall() was
    called with no members= — so symlinks (never vetted) were extracted anyway,
    and `x -> /etc` plus `x/passwd` writes outside the target."""

    def build(tar: tarfile.TarFile) -> None:
        link = tarfile.TarInfo("escape")
        link.type = tarfile.SYMTYPE
        link.linkname = str(tmp_path / "outside")
        tar.addfile(link)
        _add_file(tar, "escape/passwd")

    src = _tar_with(tmp_path, build)
    dest = tmp_path / "dest"
    dest.mkdir()
    (tmp_path / "outside").mkdir()
    with tarfile.open(src) as tar:
        with pytest.raises(UnsafeMember):
            safe_extract(tar, dest)
    assert list((tmp_path / "outside").iterdir()) == []
    assert list(dest.iterdir()) == []
