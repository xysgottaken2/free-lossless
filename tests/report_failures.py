"""Republish a failing unittest log as GitHub Actions error annotations.

Raw Actions logs are not always reachable from tooling, while the check-run
annotations API is; turning the failure text into ``::error::`` workflow commands
keeps Windows-only failures diagnosable from the command line.

A workflow command ends at the end of its line, and GitHub stores the annotation
message literally (it does not decode ``%0A``), so log lines are joined with a
visible separator instead of newlines.
"""
from pathlib import Path
import sys


MAX_ANNOTATIONS = 6
# GitHub truncates an annotation around 4 KB, so a chunk bigger than that loses its
# own end — which is where an assertion message lives.
MAX_CHARS = 3800
MAX_LINE = 300
HEAD_LINES = 40
TAIL_LINES = 200
SEPARATOR = " | "
EMPTY_LOG_NOTE = "unittest failed without producing output"
BLOCK_PREFIXES = ("FAIL:", "ERROR:", "Traceback (most recent call last):")


def relevant_lines(text, status=None, head=HEAD_LINES, tail=TAIL_LINES, max_line=MAX_LINE):
    """Keep the head (startup errors) and the tail (failure details and summary)."""
    lines = [line.strip()[:max_line] for line in text.splitlines() if line.strip()]
    if not text.strip():
        lines = [EMPTY_LOG_NOTE]
    if status is not None:
        lines.append(f"unittest exit status: {status}")
    if len(lines) <= head + tail:
        return lines
    return lines[:head] + [f"... middle of the log omitted ({len(lines) - head - tail} lines) ..."] + lines[-tail:]


def pack(lines, max_chars=MAX_CHARS):
    """Split lines into single-line annotation bodies that fit GitHub's limit."""
    chunks = []
    current = []
    size = 0
    for line in lines:
        if current and size + len(line) + len(SEPARATOR) > max_chars:
            chunks.append(current)
            current = []
            size = 0
        current.append(line)
        size += len(line) + len(SEPARATOR)
    if current:
        chunks.append(current)
    return chunks


def failure_blocks(text, max_line=MAX_LINE):
    """The failing tests, in log order, each with the end of its traceback.

    The useful part of a traceback is its last lines (the assertion), so when a block
    is longer than one annotation it is trimmed from the front, not from the back.
    """
    lines = [line.rstrip()[:max_line] for line in text.splitlines()]
    blocks = []
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("FAIL:", "ERROR:")):
            if current:
                blocks.append(current)
            current = [stripped]
        elif current is not None:
            if stripped.startswith(("Ran ", "OK", "FAILED")):
                blocks.append(current)
                current = None
            elif stripped:
                current.append(stripped)
    if current:
        blocks.append(current)
    return blocks


def merge(bodies, max_chars=MAX_CHARS):
    """Join small neighbouring chunks so a short log stays in one annotation."""
    merged = []
    for body in bodies:
        if merged and len(SEPARATOR.join(merged[-1] + body)) <= max_chars:
            merged[-1] = merged[-1] + body
        else:
            merged.append(list(body))
    return merged


def annotation_chunks(text, status=None, max_annotations=MAX_ANNOTATIONS, max_chars=MAX_CHARS):
    """Single-line ``::error::`` commands: the failures first, then the log excerpts.

    Order matters because GitHub truncates long annotations: a failing test and its
    assertion must never be lost behind the head of a verbose log.
    """
    bodies = []
    for block in failure_blocks(text):
        # Keep the end of a long block: that is where the assertion message is.
        packed = pack(block, max_chars)
        if packed:
            bodies.append(packed[-1])
    summary = [line.strip()[:MAX_LINE] for line in text.splitlines()
               if line.strip().startswith(("Ran ", "OK", "FAILED"))]
    if status is not None:
        summary.append(f"unittest exit status: {status}")
    bodies.extend(pack(summary, max_chars) or [[EMPTY_LOG_NOTE]])

    excerpts = pack([line[:MAX_LINE] for line in relevant_lines(text)[-TAIL_LINES:] if line], max_chars)
    slots = max(1, max_annotations - len(bodies))
    if len(excerpts) > slots:
        bodies.append(["... earlier log lines omitted ..."])
        excerpts = excerpts[-slots:]
    bodies.extend(excerpts)
    return [f"::error::{SEPARATOR.join(body)}" for body in merge(bodies)[:max_annotations]]


def main(argv):
    if len(argv) < 2:
        print("usage: report_failures.py <log file> [exit status]", file=sys.stderr)
        return 2
    text = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    status = argv[2] if len(argv) > 2 else None
    for chunk in annotation_chunks(text, status):
        print(chunk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
