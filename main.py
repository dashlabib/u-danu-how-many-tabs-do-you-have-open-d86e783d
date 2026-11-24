#!/usr/bin/env python3
"""Publish the honest count of open browser tabs, for the make.fun
bounty "How Many Tabs Do You Have Open?".

The count lives in ``entry.txt`` next to this file: one number in
digits and nothing else, the honest count of browser tabs open at
the moment it was sent — high enough to surprise, low enough to
believe, a number that hints at a life behind it. This program
reads that file as raw bytes, decodes it as UTF-8, checks the
number against the bounty gate (1 to 5 characters, not only white
space, digits only, exactly one number, believable as a real tab
count), and publishes the raw bytes verbatim to ``entry.txt`` in
the output directory. Publishing is byte-for-byte: ``entry.txt``
carries no trailing newline, and the published file is identical
to the source file, byte for byte. After writing, the program
reads the published file back and compares bytes; a mismatch is
a hard failure.

Standard library only: no network access, no clock reads, no
randomness, so two runs always produce identical output.

The output directory is ``--output-dir`` when given, else
``$MAKEFUN_OUTPUT_DIR`` when set, else ``/output``. Pass
``--verify-only`` to check the count without writing anything.
"""

import argparse
import os
import sys
import typing
from pathlib import Path
from typing import NamedTuple

DEFAULT_MAX_CHARS = 5
MIN_CHARS = 1
DEFAULT_OUTPUT_DIR = "/output"
ENTRY_FILENAME = "entry.txt"

# A tab count above this reads as a number picked to shock, not an
# honest answer a real person could have open right now.
MAX_BELIEVABLE_TABS = 999


class Entry(NamedTuple):
    """One entry, kept as a pair so the two can never drift apart.

    ``raw`` is the exact bytes that get published verbatim;
    ``text`` is those bytes decoded as UTF-8, which the gate
    checks. A function that takes an ``Entry`` validates the same
    bytes it publishes.
    """

    raw: bytes
    text: str


def entry_path() -> Path:
    """Return the path of the entry file shipped with this program."""
    return Path(__file__).resolve().parent / ENTRY_FILENAME


def load_raw(path: Path) -> bytes:
    """Read the entry file as raw bytes, failing loudly if unreadable."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise SystemExit(f"entry file not found: {path}")
    except OSError as exc:
        raise SystemExit(f"cannot read entry file {path}: {exc}")


def decode(raw: bytes) -> str:
    """Decode raw entry bytes as UTF-8, keeping every byte's meaning.

    A one-number entry carries no trailing newline to strip: the
    file is the number and nothing else, so decoding returns the
    text exactly as stored. Any whitespace in it is part of the
    entry and is rejected by :func:`validate` below.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"entry is not valid UTF-8: {exc}")


def load_entry() -> Entry:
    """Read the shipped entry file and return it as an ``Entry``.

    The raw bytes are what gets published verbatim; the decoded
    text is what the gate checks. Keeping the pair together means
    no caller can validate one file and publish another.
    """
    path = entry_path()
    raw = load_raw(path)
    return Entry(raw=raw, text=decode(raw))


def fail(message: str) -> "typing.NoReturn":
    """Abort with a single clear error line on stderr (exit code 1)."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def shape_violations(text: str, max_chars: int) -> list:
    """Check the text's shape: length, whitespace, controls.

    These are the sealed scorer's rules, independent of what the
    number says. An empty or whitespace-only text short-circuits
    the rest: no other shape rule can be judged on nothing.
    """
    problems = []
    if not text or text.isspace():
        problems.append("entry is empty or only white space")
        return problems
    if len(text) < MIN_CHARS:
        problems.append(
            f"entry is {len(text)} characters, below the "
            f"{MIN_CHARS}-character minimum"
        )
    if len(text) > max_chars:
        problems.append(
            f"entry is {len(text)} characters, over the "
            f"{max_chars}-character limit"
        )
    if any(ch.isspace() for ch in text):
        problems.append("entry must be exactly one number, with no spaces")
    bad = [ch for ch in text if ord(ch) < 32 or ord(ch) == 127]
    if bad:
        problems.append(
            "entry must not contain control characters "
            f"(found U+{ord(bad[0]):04X})"
        )
    return problems


def count_profile(text: str) -> dict:
    """Measure the count: its value and its magnitude band.

    ``band`` is the story the number tells the judge — ``modest``
    for a tidy browser, ``hoarder`` for a lived-in one, ``extreme``
    for a count straining belief. The band is descriptive only;
    the believability cap in :func:`count_violations` is what
    refuses a number. A non-digit text has no profile.
    """
    if not text.isdigit():
        return {"value": None, "band": "not-a-number"}
    value = int(text)
    if value < 10:
        band = "modest"
    elif value <= MAX_BELIEVABLE_TABS:
        band = "hoarder"
    else:
        band = "extreme"
    return {"value": value, "band": band}


def count_violations(text: str) -> list:
    """Check the text is one believable tab count, digits only.

    Exactly one number in digits, with no words, no punctuation
    and no second number — and a number a real person could have
    open right now, not an absurd figure picked to shock.
    """
    problems = []
    profile = count_profile(text)
    if profile["value"] is None:
        problems.append(
            "entry must be digits only "
            "(no words, punctuation or other characters)"
        )
        return problems
    count = profile["value"]
    if count < 1:
        problems.append("entry must be at least 1 tab")
    if profile["band"] == "extreme":
        problems.append(
            f"entry of {count} tabs is not believable as an "
            f"honest count (over {MAX_BELIEVABLE_TABS})"
        )
    return problems


def gate_violations(text: str, max_chars: int) -> list:
    """Collect every way the text breaks the bounty gate, in order.

    Shape first, then count: each violation is a plain sentence
    naming the rule and the offending detail, so one run reports
    everything wrong at once instead of stopping at the first
    problem. An empty list means the text passes the gate.
    """
    return shape_violations(text, max_chars) + count_violations(text)


def validate(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> None:
    """Reject any entry that breaks the bounty gate, naming each reason."""
    problems = gate_violations(text, max_chars)
    if problems:
        fail("; ".join(problems))


def resolve_output_dir(args: argparse.Namespace) -> Path:
    """Pick the output directory: CLI flag beats env var beats default.

    A blank ``$MAKEFUN_OUTPUT_DIR`` counts as unset rather than as
    a directory named nothing, which would otherwise fail oddly
    downstream instead of falling back to ``/output``.
    """
    if args.output_dir:
        return Path(args.output_dir)
    env_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path(DEFAULT_OUTPUT_DIR)


def describe(entry: Entry) -> str:
    """Summarise the entry in one line for success messages.

    Characters are what the gate counts; bytes are what the file
    holds; the count itself is the entry, so it is printed too,
    with its magnitude band — the story the number tells.
    """
    band = count_profile(entry.text)["band"]
    return (
        f"{len(entry.text)} characters, {len(entry.raw)} bytes, "
        f"{int(entry.text)} tabs open ({band})"
    )


def stage(raw: bytes, out_path: Path) -> Path:
    """Write the entry bytes to a temp file and verify the staged copy.

    Returns the temp path. The staging file sits beside the final
    path so the later rename stays on one filesystem. A staged copy
    that reads back different from ``raw`` is a hard failure before
    anything is published.
    """
    tmp_path = out_path.with_name(ENTRY_FILENAME + ".tmp")
    try:
        tmp_path.write_bytes(raw)
    except OSError as exc:
        raise SystemExit(f"cannot write {tmp_path}: {exc}")
    try:
        staged = tmp_path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read back {tmp_path}: {exc}")
    if staged != raw:
        raise SystemExit("staged entry does not match entry.txt")
    return tmp_path


def commit_staged(raw: bytes, tmp_path: Path, out_path: Path) -> Path:
    """Move a verified staged file into place and verify the result.

    The rename is :func:`os.replace`, so the published file appears
    whole or not at all. The final file is read back once more and
    compared byte for byte; a mismatch is a hard failure.
    """
    try:
        os.replace(tmp_path, out_path)
    except OSError as exc:
        raise SystemExit(f"cannot publish {out_path}: {exc}")
    try:
        published = out_path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read back {out_path}: {exc}")
    if published != raw:
        raise SystemExit("published entry does not match entry.txt")
    return out_path


def publish(raw: bytes, out_dir: Path) -> tuple:
    """Write the raw entry bytes verbatim and verify them by re-reading.

    Returns ``(path_written, byte_count)``. The bytes are staged by
    :func:`stage` and committed by :func:`commit_staged`, so a
    failed write can never leave a half-written ``entry.txt``
    behind, and a failed publish leaves no stale temp file: the
    ``finally`` block removes it. Raises SystemExit if the directory
    cannot be created, the write fails, or the bytes read back do
    not match the bytes written. The destination is resolved first
    so a surprising ``--output-dir`` (a symlink escaping the
    intended tree, for instance) is visible in the success message
    rather than silently honoured.
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"cannot create output directory {out_dir}: {exc}")
    out_path = out_dir.resolve() / ENTRY_FILENAME
    tmp_path = None
    try:
        tmp_path = stage(raw, out_path)
        commit_staged(raw, tmp_path, out_path)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return out_path, len(raw)


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command-line options for this publisher."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="directory to write entry.txt into "
        "(default: $MAKEFUN_OUTPUT_DIR or /output)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="validate the tab count without writing it",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"maximum entry length in characters (default: {DEFAULT_MAX_CHARS})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success (errors still go to stderr)",
    )
    return parser.parse_args(argv)


def run(argv=None) -> int:
    """Load, validate, and publish (or just verify) the entry.

    Split from :func:`main` so the flow can be driven in-process
    (a test harness can call ``run(["--verify-only"])`` and read
    its exit code) without going through the interpreter's exit.
    """
    args = parse_args(argv)
    if args.max_chars < MIN_CHARS:
        fail(f"--max-chars must be at least {MIN_CHARS}, got {args.max_chars}")
    entry = load_entry()
    validate(entry.text, args.max_chars)
    if args.verify_only:
        if not args.quiet:
            print(f"Valid: {describe(entry)}")
        return 0
    out_path, byte_count = publish(entry.raw, resolve_output_dir(args))
    if not args.quiet:
        print(f"Wrote {describe(entry)} to {out_path}")
    return 0


def main(argv=None) -> int:
    """Command-line entry point: run the publisher and exit."""
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
