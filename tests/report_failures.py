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
MAX_CHARS = 6000
MAX_LINE = 300
HEAD_LINES = 60
TAIL_LINES = 240
SEPARATOR = " | "
EMPTY_LOG_NOTE = "unittest failed without producing output"


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


def annotation_chunks(text, status=None, max_annotations=MAX_ANNOTATIONS, max_chars=MAX_CHARS):
    """Group log lines into single-line ``::error::`` commands, newest output last."""
    chunks = []
    current = []
    size = 0
    for line in relevant_lines(text, status):
        if current and size + len(line) + len(SEPARATOR) > max_chars:
            chunks.append(current)
            current = []
            size = 0
        current.append(line)
        size += len(line) + len(SEPARATOR)
    if current:
        chunks.append(current)
    if len(chunks) > max_annotations:
        # Failure details and the summary live at the end, so drop the oldest chunks.
        dropped = len(chunks) - (max_annotations - 1)
        chunks = [["... earlier log lines omitted ..."]] + chunks[dropped:]
    return [f"::error::{SEPARATOR.join(chunk)}" for chunk in chunks]


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
