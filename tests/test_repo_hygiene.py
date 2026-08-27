# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Repository-wide invariants about the files themselves, not their content.

These are the defects no unit test sees, because every module under test
reads fine and every assertion passes — the damage shows up later, in a
clone, in an editor, or in the next person's diff. The sibling of this
module is `test_studio_i18n.py::test_every_catalogue_file_is_actually_in_the
_repository`, which asks the same kind of question about a different thing:
would a fresh checkout get what is on this disk?
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"

# Every extension this project stores prose or code in. Deliberately a
# whitelist: a `.png` starting with those three bytes would be a coincidence,
# not a byte-order mark.
TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".css",
    ".html", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".txt", ".sql", ".sh",
}


def _tracked() -> list[Path]:
    listing = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.split()
    return [ROOT / name for name in listing]


def test_no_tracked_text_file_starts_with_a_utf8_bom():
    """A BOM is an editor artifact, and in a `.py` it is a loaded gun.

    Python tolerates one at byte zero, so these files imported and ran for
    months. The failure comes from *editing* them: prepend a header — a
    docstring, a license, an import — and the BOM is no longer at byte zero.
    It is now three invisible bytes in the middle of the first statement, and
    the file that worked a second ago is a `SyntaxError` whose caret points
    at nothing. Ten tracked files carried one; the same edit would have
    broken any of them.

    Fixing them is not enough, because the editor that wrote them is still
    out there. Hence the guard.
    """
    offenders = sorted(
        path.relative_to(ROOT).as_posix()
        for path in _tracked()
        if path.suffix in TEXT_SUFFIXES and path.is_file()
        and path.open("rb").read(3) == BOM)
    assert not offenders, (
        f"UTF-8 BOM at the start of: {offenders}. Save as UTF-8 without a "
        "signature — in source, the mark is artifact, not content.")


def test_no_tracked_source_file_reads_as_binary():
    """A NUL in source costs the file its history, and nothing else.

    Git decides text-or-binary by looking for a NUL in the first 8000 bytes.
    A source file that trips that check still imports, still runs, still
    passes every test about what it does — and arrives in every diff, every
    blame and every review as `Bin 0 -> 6550 bytes`. It landed exactly once,
    as a literal NUL used for a map key's separator, and nothing in the suite
    noticed because the code was correct.

    Written as a whitelist of the extensions this project stores code in, so
    a real binary that gains one of them would be the thing to explain.
    """
    offenders = [
        path.relative_to(ROOT).as_posix() for path in _tracked()
        if path.suffix in TEXT_SUFFIXES and path.is_file()
        and b"\x00" in path.open("rb").read(8000)]
    assert not offenders, (
        f"git will treat these as binary: {offenders}. A NUL byte belongs in "
        "source as an escape (\\u0000), never as itself — as itself it costs "
        "the file its diff and its blame.")


def test_the_sweep_actually_reaches_the_repository():
    """Guards the guard: a `git ls-files` that returned nothing would make
    every assertion above vacuously true."""
    tracked = _tracked()
    assert len(tracked) > 100, f"only {len(tracked)} tracked files found"
    suffixes = {p.suffix for p in tracked}
    assert {".py", ".jsx", ".md"} <= suffixes, suffixes
