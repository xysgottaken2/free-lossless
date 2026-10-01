import unittest

from report_failures import annotation_chunks, escape_workflow_data, relevant_lines


class ReportFailuresTests(unittest.TestCase):
    def test_short_log_stays_in_one_escaped_annotation(self):
        text = "test_ok ... ok\ntest_bad ... FAIL\n\n====\nFAIL: test_bad\nAssertionError: 1 != 2\n\nRan 2 tests\nFAILED (failures=1)\n"
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
        self.assertIn("line 0", lines[0])
        self.assertTrue(any("middle of the log omitted" in line for line in lines))
        self.assertIn("line 1999", lines[-1])
        chunks = annotation_chunks(text)
        self.assertLessEqual(len(chunks), 6)
        self.assertTrue(all(chunk.startswith("::error::") for chunk in chunks))
        self.assertTrue(all(len(chunk) <= 6000 for chunk in chunks))

    def test_large_log_is_split_into_bounded_annotations(self):
        text = "\n".join(f"line {index} " + "x" * 200 for index in range(5000))
        chunks = annotation_chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 6000 for chunk in chunks))

    def test_empty_or_whitespace_log_still_reports_an_error(self):
        for text in ("", "\n\n  \n"):
            with self.subTest(text=text):
                chunks = annotation_chunks(text, "2")
                self.assertEqual(len(chunks), 1)
                self.assertIn("unittest exit status: 2", chunks[0])
                self.assertIn("unittest failed without producing output", chunks[0])

    def test_workflow_data_is_escaped(self):
        self.assertEqual(escape_workflow_data("100%\nline2\r"), "100%25%0Aline2%0D")
        self.assertNotIn("\n", escape_workflow_data("a\nb"))

    def test_long_lines_are_truncated(self):
        self.assertEqual(relevant_lines("y" * 1000), ["y" * 300])
