import unittest

from report_failures import (MAX_ANNOTATIONS, MAX_CHARS, annotation_chunks, failure_blocks,
                             relevant_lines)


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

    def test_the_annotation_list_is_always_bounded(self):
        text = "\n".join(f"line {index} " + "x" * 300 for index in range(6000))
        chunks = annotation_chunks(text)
        self.assertLessEqual(len(chunks), MAX_ANNOTATIONS)
        self.assertIn("line 5999", chunks[-1])
        self.assertIn("earlier log lines omitted", " ".join(chunks))

    def test_empty_or_whitespace_log_still_reports_an_error(self):
        for text in ("", "\n\n  \n"):
            with self.subTest(text=text):
                chunks = annotation_chunks(text, "2")
                self.assertGreaterEqual(len(chunks), 1)
                joined = " ".join(chunks)
                self.assertIn("unittest failed without producing output", joined)
                self.assertIn("unittest exit status: 2", joined)

    def test_each_failing_test_gets_its_own_annotation_with_the_assertion(self):
        text = ("test_a ... ok\n\n====\nFAIL: test_a (t.A)\n----\n"
                "Traceback (most recent call last):\n"
                '  File "t.py", line 1, in test_a\n    self.assertEqual(1, 2)\n'
                "AssertionError: 1 != 2\n\n====\nERROR: test_b (t.B)\n----\n"
                "RuntimeError: boom\n\nRan 2 tests\nFAILED (failures=1, errors=1)\n")
        chunks = annotation_chunks(text, "1")
        joined = " ".join(chunks)
        self.assertIn("AssertionError: 1 != 2", chunks[0])
        self.assertIn("RuntimeError: boom", joined)
        self.assertIn("FAILED (failures=1, errors=1)", joined)
        # The failing test comes before the log excerpts, never after them.
        self.assertLess(chunks[0].index("AssertionError"), joined.index("test_a ... ok"))

    def test_the_failure_annotation_keeps_the_end_of_a_long_traceback(self):
        body = "\n".join(f"  File \"t.py\", line {index}" for index in range(200))
        text = f"FAIL: test_a (t.A)\n----\nTraceback (most recent call last):\n{body}\nAssertionError: fim\n"
        chunks = annotation_chunks(text, "1")
        self.assertIn("AssertionError: fim", chunks[0])
        self.assertLessEqual(len(chunks[0]), MAX_CHARS + len("::error::"))

    def test_failure_blocks_keep_the_order_of_the_log(self):
        text = "FAIL: primeiro\nTraceback\nERROR: segundo\nTraceback\nRan 2 tests\n"
        blocks = failure_blocks(text)
        self.assertEqual([block[0] for block in blocks], ["FAIL: primeiro", "ERROR: segundo"])

    def test_long_lines_are_truncated(self):
        self.assertEqual(relevant_lines("y" * 1000), ["y" * 300])
