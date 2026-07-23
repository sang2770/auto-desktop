import tempfile
import unittest
from types import SimpleNamespace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from live_reporter.live_reporter import (
    OCRLine,
    daily_totals,
    extract_money_near_label,
    find_session_label,
    is_end_summary,
    is_report_screen,
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

    def test_combined_label_without_repeated_week_prefix_is_narrowed(self) -> None:
        # Một số máy/Tesseract đọc thành "... LIVE nay Tuan nay".
        combined = OCRLine("Tam tinh phien LIVE nay Tuan nay", 440, 534, 493, 26)
        selected = find_session_label([combined])
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertLess(selected.right, 736)

    def test_extract_money_only_from_session_column(self) -> None:
        processed = SimpleNamespace(width=1200, height=800)
        label = OCRLine("Tam tinh phien LIVE nay", 440, 534, 288, 26)
        daily = OCRLine("$0.11", 442, 576, 111, 34)
        weekly = OCRLine("$1.65", 736, 576, 157, 34)

        amount = extract_money_near_label(processed, [label, weekly, daily], label, {"ocr_languages": "eng"})

        self.assertEqual(amount, Decimal("0.11"))

    def test_session_amount_is_lower_when_both_columns_overlap(self) -> None:
        processed = SimpleNamespace(width=1200, height=800)
        # Mô phỏng OCR trên máy khác trả về bbox nhãn quá rộng, khiến cả hai
        # số tiền đều bị coi là nằm trong cùng cột.
        label = OCRLine("Tam tinh phien LIVE nay", 440, 534, 500, 26)
        daily = OCRLine("$0.11", 442, 576, 111, 34)
        weekly = OCRLine("$1.65", 736, 576, 157, 34)

        amount = extract_money_near_label(processed, [label, weekly, daily], label, {"ocr_languages": "eng"})

        self.assertEqual(amount, Decimal("0.11"))

    def test_weekly_money_is_not_fallback_when_daily_ocr_is_missing(self) -> None:
        class ProcessedImage:
            width = 1200
            height = 800

            def crop(self, box):
                self.crop_box = box
                return self

        processed = ProcessedImage()
        label = OCRLine("Tam tinh phien LIVE nay", 440, 534, 288, 26)
        weekly = OCRLine("$1.65", 736, 576, 157, 34)
        fake_tesseract = SimpleNamespace(image_to_string=lambda *args, **kwargs: "")

        with patch.dict("sys.modules", {"pytesseract": fake_tesseract}):
            amount = extract_money_near_label(
                processed,
                [label, weekly],
                label,
                {"ocr_languages": "eng"},
            )

        self.assertIsNone(amount)
        self.assertEqual(processed.crop_box[2], label.right)

    def test_weekly_money_is_rejected_when_combined_label_was_wide(self) -> None:
        class ProcessedImage:
            width = 1200
            height = 800

            def crop(self, _box):
                return self

        processed = ProcessedImage()
        label = OCRLine("Tam tinh phien LIVE nay", 440, 534, 330, 26)
        weekly = OCRLine("$1.65", 736, 576, 157, 34)

        fake_tesseract = SimpleNamespace(image_to_string=lambda *args, **kwargs: "")
        with patch.dict("sys.modules", {"pytesseract": fake_tesseract}):
            amount = extract_money_near_label(processed, [label, weekly], label, {"ocr_languages": "eng"})

        self.assertIsNone(amount)

    def test_end_summary_markers(self) -> None:
        lines = [OCRLine("Phiên LIVE đã kết thúc", 0, 0, 300, 30)]
        self.assertTrue(is_end_summary(lines, "Phiên LIVE đã kết thúc"))
        self.assertTrue(is_end_summary([], "Thdi lugng 00:26:41 Trai nghiem LIVE cua ban"))
        self.assertTrue(is_end_summary([], "Da ket thic! 21 nguoi xem"))
        self.assertFalse(is_end_summary([], "Dang phat LIVE"))

    def test_report_screen_requires_multiple_layout_markers(self) -> None:
        self.assertFalse(is_report_screen([], "Da ket thuc $0.11"))
        self.assertFalse(is_report_screen([], "Thoi luong 00:10 Trai nghiem LIVE"))
        report_text = (
            "Thdi lugng 00:26:41 Tong so luot xem Luot chia se "
            "Kim cudng Tam tinh tuan nay Trai nghiem LIVE cua ban"
        )
        self.assertTrue(is_report_screen([], report_text))

    def test_report_screen_accepts_explicit_end_with_stat_groups(self) -> None:
        text = "Phien LIVE da ket thuc Thoi luong Tong so luot xem Follower moi Kim cuong"
        self.assertTrue(is_report_screen([], text))


class ConfigTests(unittest.TestCase):
    def test_default_config_has_post_success_delay(self) -> None:
        from live_reporter.live_reporter import DEFAULT_CONFIG, load_config
        self.assertIn("post_success_delay_seconds", DEFAULT_CONFIG)
        self.assertEqual(DEFAULT_CONFIG["post_success_delay_seconds"], 120)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = load_config(path)
            self.assertEqual(config["post_success_delay_seconds"], 120)


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


class DaemonLoopTests(unittest.TestCase):
    @patch("live_reporter.live_reporter.TelegramClient")
    @patch("live_reporter.live_reporter.find_tiktok_windows")
    @patch("live_reporter.live_reporter.capture_bbox")
    @patch("live_reporter.live_reporter.screen_change_key")
    @patch("live_reporter.live_reporter.analyze_image")
    @patch("live_reporter.live_reporter.register_result")
    @patch("live_reporter.live_reporter.time.sleep")
    def test_delay_applies_only_on_new_successful_captures(
        self, mock_sleep, mock_register, mock_analyze, mock_key, mock_capture, mock_windows, mock_telegram
    ) -> None:
        from live_reporter import live_reporter
        from live_reporter.live_reporter import run_daemon

        mock_windows.return_value = [(101, "TikTok LIVE Studio", (0, 0, 800, 600))]
        mock_capture.return_value = "fake_image"
        mock_key.return_value = "hash123"
        fake_result = SimpleNamespace(amount=Decimal("1.00"), signature="sig123")
        mock_analyze.return_value = fake_result
        mock_register.return_value = True

        def stop_after_one_sleep(*args, **kwargs):
            live_reporter.STOP_REQUESTED = True

        mock_sleep.side_effect = stop_after_one_sleep

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            config = {
                "telegram_bot_token": "token",
                "telegram_chat_id": "123",
                "scan_interval_seconds": 5,
                "post_success_delay_seconds": 0.8,
            }

            # Lan 1: ket qua OCR moi (register_result -> True)
            live_reporter.STOP_REQUESTED = False
            run_daemon(config, state_path, once=False)
            self.assertTrue(mock_sleep.called)
            first_sleep_arg = mock_sleep.call_args[0][0]
            self.assertLess(first_sleep_arg, 0.9)

            mock_sleep.reset_mock()
            mock_sleep.side_effect = stop_after_one_sleep
            # Lan 2: ket qua OCR giu nguyen va da duoc register truoc do (register_result -> False)
            mock_register.return_value = False
            live_reporter.STOP_REQUESTED = False
            run_daemon(config, state_path, once=False)
            self.assertTrue(mock_sleep.called)
            second_sleep_arg = mock_sleep.call_args[0][0]
            self.assertEqual(second_sleep_arg, 1.0)


if __name__ == "__main__":
    unittest.main()
