"""
Unit tests for humanized browser interaction methods (utils/browser.py).
"""

import unittest
from unittest.mock import MagicMock, patch

from utils.browser import BrowserManager


class TestBrowserSimulation(unittest.TestCase):
    def test_human_type_sequentially(self):
        """Tests that human_type invokes press_sequentially with jitter delays."""
        mock_locator = MagicMock()
        mock_locator.press_sequentially = MagicMock()

        BrowserManager.human_type(mock_locator, "2", min_delay_ms=10, max_delay_ms=20)
        mock_locator.click.assert_called_once()
        mock_locator.press_sequentially.assert_called_once()

    def test_human_type_long_text_batch(self):
        """Tests that long paragraphs (e.g. cover letters) use direct fill for performance."""
        mock_locator = MagicMock()
        long_text = "A" * 120

        BrowserManager.human_type(mock_locator, long_text)
        mock_locator.fill.assert_called_once_with(long_text)

    def test_human_move_and_click_with_box(self):
        """Tests curved mouse movement when bounding box is available."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.bounding_box.return_value = {
            "x": 100.0,
            "y": 200.0,
            "width": 80.0,
            "height": 30.0,
        }

        BrowserManager.human_move_and_click(mock_page, mock_locator)
        # Mouse should have moved at least twice (jitter step and target step)
        self.assertGreaterEqual(mock_page.mouse.move.call_count, 2)
        mock_page.mouse.down.assert_called_once()
        mock_page.mouse.up.assert_called_once()

    def test_human_move_and_click_fallback(self):
        """Tests fallback to direct click when bounding box is absent."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.bounding_box.return_value = None

        BrowserManager.human_move_and_click(mock_page, mock_locator)
        mock_locator.click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
