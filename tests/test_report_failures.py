import unittest

from report_failures import MAX_ANNOTATIONS, MAX_CHARS, annotation_chunks, relevant_lines


class ReportFailuresTests(unittest.TestCase):
    def test_short_log_stays_in_one_single_line_annotation(self):
        text = ("test_ok ... ok\ntest_bad ... FAIL\n\n====\nFAIL: test_bad\n"
                "AssertionError: 1 != 2\n\nRan 2 tests\nFAILED (failures=1)\n")
        chunks = annotation_chunks(text, "1")
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("::error::"))
        self.assertNotIn("\n", chunks[0])
        self.assertIn("AssertionError: 1 != 2", chunks[0])
        self.assertIn("FAILED (failures=1)", chunks[0])
        self.assertIn("unittest exit status: 1", chunks[0])

    def test_long_log_keeps_the_head_and_the_tail(self):
        text = "\n".join(f"line {index} " + "x" * 100 for index in range(2000))
        lines = relevant_lines(text)
        self.assertTrue(lines[0].startswith("line 0"))
        self.assertTrue(any("middle of the log omitted" in line for line in lines))
        self.assertTrue(lines[-1].startswith("line 1999"))

    def test_large_log_is_split_into_bounded_single_line_annotations(self):
        text = "\n".join(f"line {index} " + "x" * 200 for index in range(5000))
        chunks = annotation_chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(len(chunks), MAX_ANNOTATIONS)
        for chunk in chunks:
            self.assertTrue(chunk.startswith("::error::"))
            self.assertNotIn("\n", chunk)
            self.assertLessEqual(len(chunk), MAX_CHARS + len("::error::"))
        self.assertIn("line 4999", chunks[-1])

    def test_oldest_chunks_are_dropped_only_when_necessary(self):
        text = "\n".join(f"line {index} " + "x" * 300 for index in range(6000))
        chunks = annotation_chunks(text)
        self.assertLessEqual(len(chunks), MAX_ANNOTATIONS)
        self.assertIn("earlier log lines omitted", chunks[0])

    def test_empty_or_whitespace_log_still_reports_an_error(self):
        for text in ("", "\n\n  \n"):
            with self.subTest(text=text):
                chunks = annotation_chunks(text, "2")
                self.assertEqual(len(chunks), 1)
                self.assertIn("unittest failed without producing output", chunks[0])
                self.assertIn("unittest exit status: 2", chunks[0])

    def test_long_lines_are_truncated(self):
        self.assertEqual(relevant_lines("y" * 1000), ["y" * 300])
