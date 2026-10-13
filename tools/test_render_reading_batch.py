import unittest
from pathlib import Path
from unittest.mock import patch

from render_reading_batch import render_batch


class ReadingBatchTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("example.pdf")
        self.report = {"page_count": 20, "pages": [{} for _ in range(20)]}

    def test_invalid_ranges_never_render(self):
        with patch("render_reading_batch.checked_source", return_value=self.source), \
             patch("render_reading_batch.report_for", return_value=(self.report, None)), \
             patch("render_reading_batch.render_page") as render:
            for start, end in [(0, 1), (1, 21), (5, 4), (1, 13)]:
                with self.assertRaises(ValueError):
                    render_batch(self.source, start, end)
            render.assert_not_called()

    def test_results_keep_page_order(self):
        with patch("render_reading_batch.checked_source", return_value=self.source), \
             patch("render_reading_batch.report_for", return_value=(self.report, None)), \
             patch("render_reading_batch.render_page", side_effect=lambda path, page: {"page": page, "status": "rendered_not_reviewed"}):
            results = render_batch(self.source, 3, 5)
            self.assertEqual([row["page"] for row in results], [3, 4, 5])
            self.assertTrue(all(row["status"] == "rendered_not_reviewed" for row in results))
