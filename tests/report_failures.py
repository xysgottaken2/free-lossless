"""Republish a failing unittest log as GitHub Actions error annotations.

Raw Actions logs are not always reachable from tooling, while the check-run
annotations API is; turning the failure text into ``::error::`` workflow commands
keeps Windows-only failures diagnosable from the command line.

Newlines have to be escaped (``%0A``) because the runner ends a workflow command
at the end of the line; unescaped text would lose everything after the first line.
"""
from pathlib import Path
import sys


MAX_ANNOTATIONS = 6
MAX_CHARS = 6000
MAX_LINE = 300
HEAD_LINES = 60
TAIL_LINES = 240


def escape_workflow_data(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def relevant_lines(text, head=HEAD_LINES, tail=TAIL_LINES, max_line=MAX_LINE):
    """Keep the head (startup errors) and the tail (failure details and summary)."""
    lines = [line.rstrip()[:max_line] for line in text.splitlines() if line.strip()]
    if len(lines) <= head + tail:
        return lines
    return lines[:head] + [f"... middle of the log omitted ({len(lines) - head - tail} lines) ..."] + lines[-tail:]


def annotation_chunks(text, status=None, max_annotations=MAX_ANNOTATIONS, max_chars=MAX_CHARS):
    """Group log lines into ``::error::`` commands, preserving their original order."""
    lines = relevant_lines(text)
    if status is not None:
        lines.append(f"unittest exit status: {status}")
    if not lines:
        lines = ["unittest failed without producing output"]
    chunks = []
    current = ""
    for line in lines:
        if current and len(current) + len(line) + 1 > max_chars and len(chunks) < max_annotations - 1:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current:
        chunks.append(current)
    return [f"::error::{escape_workflow_data(chunk)}" for chunk in chunks]


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
