import unittest

from report_failures import annotation_chunks, failure_lines


class ReportFailuresTests(unittest.TestCase):
    def test_short_log_stays_in_one_annotation(self):
        text = "test_ok ... ok\ntest_bad ... FAIL\n\n====\nFAIL: test_bad\nAssertionError: 1 != 2\n\nRan 2 tests\nFAILED (failures=1)\n"
        chunks = annotation_chunks(text)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("::error::"))
        self.assertIn("AssertionError: 1 != 2", chunks[0])
        self.assertIn("FAILED (failures=1)", chunks[0])

    def test_long_log_is_split_into_bounded_annotations(self):
        text = "\n".join(f"line {index} " + "x" * 200 for index in range(2000))
        chunks = annotation_chunks(text)
        self.assertLessEqual(len(chunks), 8)
        self.assertTrue(all(chunk.startswith("::error::") for chunk in chunks))
        self.assertTrue(all(len(chunk) <= 6000 for chunk in chunks))
        # The most recent output, which holds the failure details, must survive.
        self.assertIn("line 1999", chunks[-1])

    def test_empty_or_whitespace_log_still_reports_an_error(self):
        for text in ("", "\n\n  \n"):
            with self.subTest(text=text):
                chunks = annotation_chunks(text)
                self.assertEqual(chunks, ["::error::unittest failed without producing output"])

    def test_long_lines_are_truncated(self):
        self.assertEqual(failure_lines("y" * 1000), ["y" * 400])
