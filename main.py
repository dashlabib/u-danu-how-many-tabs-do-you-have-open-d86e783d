#!/usr/bin/env python3
"""Publish the honest count of open browser tabs, for the make.fun
bounty "How Many Tabs Do You Have Open?" — revision v3 (rule
registry).

The count lives in ``entry.txt`` next to this file: one number in
digits and nothing else, the honest count of browser tabs open at
the moment it was sent — high enough to surprise, low enough to
believe, a number that hints at a life behind it. The gate here is
a registry of small rule functions: each rule takes the decoded
text and the length limit and returns one violation message, or
``None`` when the text passes that rule. :func:`evaluate` runs the
registry and collects every violation at once; :func:`publish`
then writes the raw bytes verbatim to ``entry.txt`` in the output
directory, verifying the staged copy and the published file by
SHA-256 as well as by direct byte comparison. Publishing is
byte-for-byte: ``entry.txt`` carries no trailing newline, and the
published file is identical to the source file, byte for byte.

Standard library only: no network access, no clock reads, no
randomness, so two runs always produce identical output.

The output directory is ``--output-dir`` when given, else
``$MAKEFUN_OUTPUT_DIR`` when set, else ``/output``. Pass
``--verify-only`` to check the count without writing anything.
"""

import argparse
import hashlib
import os
import sys
import tempfile
import typing
from dataclasses import dataclass
from pathlib import Path

MAX_CHARS = 5
MIN_CHARS = 1
DEFAULT_OUTPUT_DIR = "/output"
ENTRY_FILENAME = "entry.txt"

Rule = typing.Callable[[str, int], typing.Optional[str]]

# A tab count above this reads as a number picked to shock, not an
# honest answer a real person could have open right now.
MAX_BELIEVABLE_TABS = 999


@dataclass(frozen=True)
class Entry:
    """One entry, kept as a pair so the two can never drift apart.

    ``raw`` is the exact bytes that get published verbatim;
    ``text`` is those bytes decoded as UTF-8, which the gate
    checks. A function that takes an ``Entry`` validates the same
    bytes it publishes.
    """

    raw: bytes
    text: str

    @classmethod
    def load(cls) -> "Entry":
        """Read the shipped ``entry.txt`` and decode it for the gate.

        A one-number entry carries no trailing newline to strip: the
        file is the number and nothing else, so decoding returns the
        text exactly as stored. Any whitespace in it is part of the
        entry and is rejected by the rules.
        """
        path = Path(__file__).resolve().parent / ENTRY_FILENAME
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise SystemExit(f"entry file not found: {path}")
        except OSError as exc:
            raise SystemExit(f"cannot read entry file {path}: {exc}")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SystemExit(f"entry is not valid UTF-8: {exc}")
        return cls(raw=raw, text=decoded)


def rule_not_empty(text: str, limit: int) -> typing.Optional[str]:
    """Reject an entry that is empty or only white space.

    This rule runs before the registry: no other rule can be
    judged on nothing, so it short-circuits the rest.
    """
    if not text or text.isspace():
        return "entry is empty or only white space"
    return None


def rule_length(text: str, limit: int) -> typing.Optional[str]:
    """Reject a count outside the 1-to-limit character gate."""
    if len(text) < MIN_CHARS:
        return (
            f"entry is {len(text)} characters, below the "
            f"{MIN_CHARS}-character minimum"
        )
    if len(text) > limit:
        return (
            f"entry is {len(text)} characters, over the "
            f"{limit}-character limit"
        )
    return None


def rule_no_space(text: str, limit: int) -> typing.Optional[str]:
    """Reject any whitespace: the entry must be exactly one number."""
    if any(ch.isspace() for ch in text):
        return "entry must be exactly one number, with no spaces"
    return None


def rule_no_controls(text: str, limit: int) -> typing.Optional[str]:
    """Reject control characters anywhere in the count."""
    for ch in text:
        if ord(ch) < 32 or ord(ch) == 127:
            return (
                "entry must not contain control characters "
                f"(found U+{ord(ch):04X})"
            )
    return None


def measure(text: str) -> dict:
    """Measure the count: its value and its magnitude band.

    ``band`` is the story the number tells the judge — ``modest``
    for a tidy browser, ``hoarder`` for a lived-in one, ``extreme``
    for a count straining belief. The band is descriptive only;
    the believability cap in :func:`rule_believable` is what
    refuses a number. A non-digit text has no measure.
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


def rule_believable(text: str, limit: int) -> typing.Optional[str]:
    """Reject a count that is not one believable number, digits only.

    Exactly one number in digits, with no words, no punctuation
    and no second number — and a number a real person could have
    open right now, not an absurd figure picked to shock.
    """
    measured = measure(text)
    if measured["value"] is None:
        return (
            "entry must be digits only "
            "(no words, punctuation or other characters)"
        )
    count = measured["value"]
    if count < 1:
        return "entry must be at least 1 tab"
    if measured["band"] == "extreme":
        return (
            f"entry of {count} tabs is not believable as an "
            f"honest count (over {MAX_BELIEVABLE_TABS})"
        )
    return None


RULES: typing.List[Rule] = [
    rule_length,
    rule_no_space,
    rule_no_controls,
    rule_believable,
]


def evaluate(text: str, limit: int) -> list:
    """Run the rule registry and collect every violation, in order.

    An empty or whitespace-only text short-circuits the registry.
    Otherwise each rule contributes at most one message, so one run
    reports everything wrong at once. An empty list means the text
    passes the gate.
    """
    head = rule_not_empty(text, limit)
    if head is not None:
        return [head]
    return [msg for rule in RULES if (msg := rule(text, limit)) is not None]


def pick_output_dir(cli_dir) -> Path:
    """Pick the output directory: CLI flag beats env var beats default."""
    if cli_dir:
        return Path(cli_dir)
    env_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path(DEFAULT_OUTPUT_DIR)


def digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def publish(entry: Entry, out_dir: Path) -> Path:
    """Write the raw entry bytes verbatim and verify them twice.

    Returns the path written. The bytes are staged in a temporary
    file beside the final path and moved into place with
    :func:`os.replace` only after the staged copy matches the
    source by SHA-256, so a failed write can never leave a
    half-written ``entry.txt`` behind. The published file is then
    read back and compared byte for byte and by digest; a mismatch
    at either step is a hard failure.
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"cannot create output directory {out_dir}: {exc}")
    out_path = out_dir.resolve() / ENTRY_FILENAME
    staged_name = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=ENTRY_FILENAME + ".", dir=str(out_path.parent), delete=False
        ) as handle:
            staged_name = handle.name
            handle.write(entry.raw)
        staged = Path(staged_name).read_bytes()
        if digest(staged) != digest(entry.raw):
            raise SystemExit("staged entry does not match entry.txt")
        try:
            os.replace(staged_name, out_path)
        except OSError as exc:
            raise SystemExit(f"cannot publish {out_path}: {exc}")
    finally:
        if staged_name is not None:
            try:
                Path(staged_name).unlink(missing_ok=True)
            except OSError:
                pass
    try:
        published = out_path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read back {out_path}: {exc}")
    if published != entry.raw or digest(published) != digest(entry.raw):
        raise SystemExit("published entry does not match entry.txt")
    return out_path


def summary(entry: Entry) -> str:
    """Summarise the entry in one line for success messages.

    Characters are what the gate counts; bytes are what the file
    holds; the count itself is the entry, so it is printed too,
    with its magnitude band — the story the number tells.
    """
    band = measure(entry.text)["band"]
    return (
        f"{len(entry.text)} characters, {len(entry.raw)} bytes, "
        f"{int(entry.text)} tabs open ({band})"
    )


def parse_options(argv=None) -> argparse.Namespace:
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
        default=MAX_CHARS,
        help=f"maximum entry length in characters (default: {MAX_CHARS})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success (errors still go to stderr)",
    )
    return parser.parse_args(argv)


def run(argv=None) -> int:
    """Load, validate, and publish (or just verify) the entry."""
    args = parse_options(argv)
    if args.max_chars < MIN_CHARS:
        print(
            f"error: --max-chars must be at least {MIN_CHARS}, "
            f"got {args.max_chars}",
            file=sys.stderr,
        )
        return 1
    entry = Entry.load()
    problems = evaluate(entry.text, args.max_chars)
    if problems:
        print(f"error: {'; '.join(problems)}", file=sys.stderr)
        return 1
    if args.verify_only:
        if not args.quiet:
            print(f"Valid: {summary(entry)}")
        return 0
    out_path = publish(entry, pick_output_dir(args.output_dir))
    if not args.quiet:
        print(f"Wrote {summary(entry)} to {out_path}")
    return 0


def main(argv=None) -> int:
    """Command-line entry point: run the publisher and exit."""
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
