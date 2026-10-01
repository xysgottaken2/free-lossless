"""Republish a failing unittest log as GitHub Actions error annotations.

Raw Actions logs are not always reachable from tooling, while the check-run
annotations API is; turning the failure text into ``::error::`` workflow commands
keeps Windows-only failures diagnosable from the command line.
"""
from pathlib import Path
import sys


MAX_ANNOTATIONS = 8
MAX_CHARS = 6000
MAX_LINE = 400
TAIL_LINES = 160


def failure_lines(text, tail=TAIL_LINES, max_line=MAX_LINE):
    """Keep the end of the log, where unittest prints failure details and the summary."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return [line[:max_line] for line in lines[-tail:]]


def annotation_chunks(text, max_annotations=MAX_ANNOTATIONS, max_chars=MAX_CHARS):
    """Group log lines into ``::error::`` commands, preserving their original order."""
    lines = failure_lines(text)
    if not lines:
        return ["::error::unittest failed without producing output"]
    chunks = ["::error::"]
    size = len(chunks[0])
    for line in lines:
        if size + len(line) + 3 > max_chars and len(chunks) < max_annotations:
            chunks[-1] = chunks[-1].rstrip() + " ..."
            chunks.append("::error::")
            size = len(chunks[-1])
        chunks[-1] += f"{line}\n"
        size += len(line) + 1
    return [chunk.rstrip() for chunk in chunks]


def main(argv):
    if len(argv) != 2:
        print("usage: report_failures.py <log file>", file=sys.stderr)
        return 2
    text = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    for chunk in annotation_chunks(text):
        print(chunk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
