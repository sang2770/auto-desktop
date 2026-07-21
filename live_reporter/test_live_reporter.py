import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from live_reporter.live_reporter import (
    OCRLine,
    daily_totals,
    find_session_label,
    is_end_summary,
    load_state,
    normalize_text,
    parse_money,
    save_state,
)


class TextParsingTests(unittest.TestCase):
    def test_normalize_vietnamese(self) -> None:
        self.assertEqual(normalize_text("Tạm tính phiên LIVE này"), "tam tinh phien live nay")

    def test_parse_money(self) -> None:
        self.assertEqual(parse_money("$ 0.54"), Decimal("0.54"))
        self.assertEqual(parse_money("S0,11"), Decimal("0.11"))
        self.assertEqual(parse_money("0.75", allow_bare=True), Decimal("0.75"))
        self.assertIsNone(parse_money("6.91"))

    def test_find_session_label_not_week_label(self) -> None:
        lines = [
            OCRLine("Tạm tính tuần này", 400, 100, 150, 25),
            OCRLine("Tam tinh phien LIVE nay", 200, 100, 180, 25),
        ]
        self.assertEqual(find_session_label(lines), lines[1])

    def test_combined_session_and_week_label_is_narrowed_to_first_column(self) -> None:
        combined = OCRLine("Tam tinh phien LIVE nay Tam tinh tuan nay", 200, 100, 500, 25)
        selected = find_session_label([combined])
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertLess(selected.width, combined.width)
        self.assertEqual(selected.left, combined.left)

    def test_end_summary_markers(self) -> None:
        lines = [OCRLine("Phiên LIVE đã kết thúc", 0, 0, 300, 30)]
        self.assertTrue(is_end_summary(lines, "Phiên LIVE đã kết thúc"))
        self.assertTrue(is_end_summary([], "Thdi lugng 00:26:41 Trai nghiem LIVE cua ban"))
        self.assertTrue(is_end_summary([], "Da ket thic! 21 nguoi xem"))
        self.assertFalse(is_end_summary([], "Dang phat LIVE"))


class StateTests(unittest.TestCase):
    def test_state_round_trip_and_daily_totals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {
                "last_daily_report_date": "",
                "sessions": [
                    {"detected_at": "2026-07-21T10:00:00", "amount_usd": "0.11", "diamond_count": 30},
                    {"detected_at": "2026-07-21T12:00:00", "amount_usd": "0.54", "diamond_count": 139},
                    {"detected_at": "2026-07-20T12:00:00", "amount_usd": "0.21", "diamond_count": 53},
                ],
            }
            save_state(path, state)
            restored = load_state(path)
            self.assertEqual(daily_totals(restored, date(2026, 7, 21)), (2, Decimal("0.65"), 169))


if __name__ == "__main__":
    unittest.main()
