#!/usr/bin/env python3
"""Theo doi man hinh ket qua TikTok LIVE Studio va gui bao cao Telegram."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Iterable


APP_NAME = "AutoDesktopLiveReporter"
DEFAULT_CONFIG: dict[str, Any] = {
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "window_title_keywords": ["TikTok LIVE Studio", "TikTok Live Studio"],
    "scan_interval_seconds": 15,
    "daily_report_time": "23:55",
    "send_empty_daily_report": False,
    "send_screenshot": False,
    "ocr_languages": "eng",
    "ocr_min_confidence": 20,
    "tesseract_cmd": "",
    "history_limit": 500,
    "debug_screenshots": False,
}


def runtime_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9$]+", " ", without_accents).strip()


@dataclass(frozen=True)
class OCRLine:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float = 0.0

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2


@dataclass(frozen=True)
class LiveResult:
    amount: Decimal
    diamond_count: int | None
    summary: str
    signature: str
    ocr_text: str
    screenshot: Any

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "amount_usd": format_money(self.amount),
            "diamond_count": self.diamond_count,
            "summary": self.summary,
            "signature": self.signature,
        }


def load_config(path: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        with path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError(f"Config phai la mot JSON object: {path}")
        config.update(raw)

    # Bien moi truong uu tien hon file de co the giu token ben ngoai source code.
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config["telegram_bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        config["telegram_chat_id"] = os.environ["TELEGRAM_CHAT_ID"]
    return config


def setup_logging(log_path: Path, verbose: bool = False) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    ]
    if verbose or sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def resolve_tesseract(configured: str) -> str:
    candidates = [configured, shutil.which("tesseract")]
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")]
    for base in program_files:
        if base:
            candidates.append(str(Path(base) / "Tesseract-OCR" / "tesseract.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    raise RuntimeError(
        "Khong tim thay Tesseract OCR. Cai Tesseract OCR va them vao PATH, "
        "hoac dien duong dan tesseract.exe vao tesseract_cmd trong config."
    )


def configure_tesseract(config: dict[str, Any]) -> None:
    import pytesseract  # type: ignore

    pytesseract.pytesseract.tesseract_cmd = resolve_tesseract(str(config.get("tesseract_cmd", "")))
    requested = str(config.get("ocr_languages", "eng"))
    installed = set(pytesseract.get_languages(config=""))
    available = [lang for lang in requested.split("+") if lang in installed]
    if not available:
        if "eng" not in installed:
            raise RuntimeError("Tesseract chua co goi ngon ngu 'eng'.")
        available = ["eng"]
    actual = "+".join(available)
    if actual != requested:
        logging.warning("OCR language '%s' chua day du; dung '%s'.", requested, actual)
    config["ocr_languages"] = actual


def prepare_image(image: Any) -> Any:
    from PIL import ImageEnhance, ImageFilter, ImageOps  # type: ignore

    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    # Anh mau co chu nho; upscale giup Tesseract doc dau cham va ky hieu $ on dinh hon.
    scale = 2 if min(gray.size) < 1000 else 1.5
    resized = gray.resize((int(gray.width * scale), int(gray.height * scale)))
    return resized.filter(ImageFilter.SHARPEN)


def _tokens_to_segments(tokens: list[dict[str, Any]]) -> list[OCRLine]:
    if not tokens:
        return []
    tokens.sort(key=lambda token: token["left"])
    groups: list[list[dict[str, Any]]] = [[tokens[0]]]
    for token in tokens[1:]:
        previous = groups[-1][-1]
        gap = token["left"] - (previous["left"] + previous["width"])
        typical_height = max(token["height"], previous["height"], 1)
        if gap > max(36, typical_height * 2.2):
            groups.append([token])
        else:
            groups[-1].append(token)

    segments: list[OCRLine] = []
    for group in groups:
        left = min(token["left"] for token in group)
        top = min(token["top"] for token in group)
        right = max(token["left"] + token["width"] for token in group)
        bottom = max(token["top"] + token["height"] for token in group)
        segments.append(
            OCRLine(
                text=" ".join(token["text"] for token in group),
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                confidence=sum(token["confidence"] for token in group) / len(group),
            )
        )
    return segments


def read_ocr_lines(image: Any, config: dict[str, Any]) -> tuple[Any, list[OCRLine], str]:
    import pytesseract  # type: ignore
    from pytesseract import Output  # type: ignore

    processed = prepare_image(image)
    data = pytesseract.image_to_data(
        processed,
        lang=str(config["ocr_languages"]),
        config="--oem 3 --psm 11 -c preserve_interword_spaces=1",
        output_type=Output.DICT,
    )
    minimum_confidence = float(config.get("ocr_min_confidence", 20))
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    all_text: list[str] = []
    for index, raw_text in enumerate(data["text"]):
        text = str(raw_text).strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1
        if not text or confidence < minimum_confidence:
            continue
        all_text.append(text)
        key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        grouped.setdefault(key, []).append(
            {
                "text": text,
                "confidence": confidence,
                "left": int(data["left"][index]),
                "top": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
            }
        )

    lines: list[OCRLine] = []
    for tokens in grouped.values():
        lines.extend(_tokens_to_segments(tokens))
    lines.sort(key=lambda line: (line.top, line.left))
    return processed, lines, " ".join(all_text)


def _similarity(value: str, target: str) -> float:
    return SequenceMatcher(None, normalize_text(value), target).ratio()


def find_session_label(lines: Iterable[OCRLine]) -> OCRLine | None:
    best: tuple[float, OCRLine] | None = None
    target = "tam tinh phien live nay"
    for line in lines:
        normalized = normalize_text(line.text)
        if "live" not in normalized:
            continue
        score = _similarity(line.text, target)
        if "phien" in normalized and ("tinh" in normalized or "tam" in normalized):
            score += 0.45
        if "tuan" in normalized:
            score -= 0.5
        if best is None or score > best[0]:
            best = (score, line)
    if not best or best[0] < 0.62:
        return None
    label = best[1]
    normalized = normalize_text(label.text)
    # Tesseract thuong ghep hai cot "phien LIVE" va "tuan nay" thanh mot line.
    # Thu hep bbox ve cot dau de khong chon nham tong theo tuan o ben phai.
    week_index = normalized.find("tam tinh tuan")
    session_index = normalized.find("tam tinh phien")
    if week_index > session_index >= 0:
        fraction = max(0.35, min(0.75, week_index / max(len(normalized), 1)))
        label = OCRLine(
            text=label.text[: max(1, int(len(label.text) * fraction))].strip(),
            left=label.left,
            top=label.top,
            width=max(1, int(label.width * fraction)),
            height=label.height,
            confidence=label.confidence,
        )
    return label


MONEY_PATTERN = re.compile(r"(?:\$|\bS)\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)", re.IGNORECASE)


def parse_money(text: str, allow_bare: bool = False) -> Decimal | None:
    compact = text.replace(" ", "")
    match = MONEY_PATTERN.search(compact)
    if not match and allow_bare:
        match = re.search(r"\b([0-9]{1,5}[.,][0-9]{1,2})\b", compact)
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if value < 0 or value > Decimal("100000"):
        return None
    return value.quantize(Decimal("0.01"))


def extract_money_near_label(processed: Any, lines: list[OCRLine], label: OCRLine, config: dict[str, Any]) -> Decimal | None:
    candidates: list[tuple[float, Decimal]] = []
    for line in lines:
        if line is label:
            continue
        amount = parse_money(line.text, allow_bare=False)
        if amount is None:
            continue
        vertical_delta = line.top - label.bottom
        horizontal_delta = abs(line.center_x - label.center_x)
        if -label.height <= vertical_delta <= max(label.height * 5, processed.height * 0.1):
            if horizontal_delta <= max(label.width * 0.9, processed.width * 0.12):
                candidates.append((abs(vertical_delta) * 2 + horizontal_delta, amount))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    # Fallback: OCR rieng vung ngay duoi nhan, chi cho phep ky tu tien te va chu so.
    import pytesseract  # type: ignore

    padding_x = max(12, int(label.width * 0.2))
    crop = processed.crop(
        (
            max(0, label.left - padding_x),
            max(0, label.bottom - 3),
            min(processed.width, label.right + padding_x),
            min(processed.height, label.bottom + max(label.height * 5, 80)),
        )
    )
    text = pytesseract.image_to_string(
        crop,
        lang=str(config["ocr_languages"]),
        config="--oem 3 --psm 7 -c tessedit_char_whitelist=$S0123456789.,",
    )
    return parse_money(text, allow_bare=True)


def is_end_summary(lines: Iterable[OCRLine], raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    if "ket thuc" in normalized:
        return True
    # Cac loi OCR pho bien voi font TikTok: "ket thic", "thdi lugng", "tr4i nghiem".
    if re.search(r"\bda ket th[a-z0-9]+", normalized):
        return True
    duration_marker = re.search(r"\bth[a-z0-9]i lu[a-z0-9]+", normalized)
    experience_marker = re.search(r"\btr[a-z0-9]i nghiem live", normalized)
    if duration_marker and experience_marker:
        return True
    for line in lines:
        line_text = normalize_text(line.text)
        if _similarity(line_text, "phien live da ket thuc") >= 0.62:
            return True
        if _similarity(line_text, "da ket thuc") >= 0.72:
            return True
    return False


def _nearby_integer(lines: list[OCRLine], label_terms: tuple[str, ...]) -> int | None:
    for label in lines:
        normalized = normalize_text(label.text)
        matches_terms = all(term in normalized for term in label_terms)
        if label_terms == ("kim", "cuong"):
            matches_terms = "kim" in normalized and (
                "cuong" in normalized
                or re.search(r"\bc[uoa][a-z]*ng\b", normalized) is not None
                or _similarity(normalized, "kim cuong") >= 0.6
            )
        if not matches_terms:
            continue
        # Co layout dat so tren cung dong, co layout dat o dong ke tiep.
        same_line = re.findall(r"\b([0-9]{1,7})\b", label.text)
        if same_line:
            return int(same_line[-1])
        candidates: list[tuple[float, int]] = []
        for line in lines:
            match = re.fullmatch(r"\D*([0-9]{1,7})\D*", line.text.strip())
            if not match:
                continue
            vertical_delta = line.top - label.bottom
            if -label.height <= vertical_delta <= label.height * 5:
                horizontal_delta = abs(line.center_x - label.center_x)
                if horizontal_delta < max(label.width, 180):
                    candidates.append((abs(vertical_delta) * 2 + horizontal_delta, int(match.group(1))))
        if candidates:
            return min(candidates, key=lambda item: item[0])[1]
    return None


def choose_summary(lines: list[OCRLine]) -> str:
    priorities = ("duoc phat truc tuyen", "thoi luong", "phien live da ket thuc", "da ket thuc")
    for priority in priorities:
        for line in lines:
            if priority in normalize_text(line.text):
                return line.text.strip()[:180]
    return "Phien LIVE da ket thuc"


def perceptual_signature(image: Any, amount: Decimal, summary: str) -> str:
    from PIL import ImageOps  # type: ignore

    # Chi bam phan noi dung chinh, bo khu chat ben phai de tranh tao phien gia khi chat thay doi.
    stable = image.crop((0, 0, int(image.width * 0.78), int(image.height * 0.78)))
    resized = ImageOps.grayscale(stable).resize((24, 24))
    if hasattr(resized, "get_flattened_data"):
        pixels = list(resized.get_flattened_data())
    else:
        pixels = list(resized.getdata())
    average = sum(pixels) / max(len(pixels), 1)
    bits = bytes(1 if pixel >= average else 0 for pixel in pixels)
    payload = bits + str(amount).encode("ascii") + normalize_text(summary).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def screen_change_key(image: Any) -> str:
    """Hash du chi tiet de bo qua OCR khi man hinh ket qua van giu nguyen."""
    from PIL import ImageOps  # type: ignore

    stable = image.crop((0, 0, int(image.width * 0.78), int(image.height * 0.78)))
    sample = ImageOps.grayscale(stable).resize((160, 90))
    return hashlib.sha256(sample.tobytes()).hexdigest()[:20]


def analyze_image(image: Any, config: dict[str, Any]) -> LiveResult | None:
    processed, lines, raw_text = read_ocr_lines(image, config)
    label = find_session_label(lines)
    if label is None or not is_end_summary(lines, raw_text):
        return None
    amount = extract_money_near_label(processed, lines, label, config)
    if amount is None:
        logging.warning("Da thay man hinh ket qua nhung khong doc duoc so tien.")
        return None
    diamonds = _nearby_integer(lines, ("kim", "cuong"))
    summary = choose_summary(lines)
    return LiveResult(
        amount=amount,
        diamond_count=diamonds,
        summary=summary,
        signature=perceptual_signature(image, amount, summary),
        ocr_text=raw_text,
        screenshot=image,
    )


def set_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def find_tiktok_windows(keywords: Iterable[str]) -> list[tuple[int, str, tuple[int, int, int, int]]]:
    if sys.platform != "win32":
        raise RuntimeError("Che do quet cua so hien chi ho tro Windows.")
    import win32gui  # type: ignore

    wanted = [keyword.casefold() for keyword in keywords]
    found: list[tuple[int, str, tuple[int, int, int, int]]] = []

    def callback(hwnd: int, _: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title or not any(keyword in title.casefold() for keyword in wanted):
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if right - left < 500 or bottom - top < 350:
            return
        found.append((hwnd, title, (left, top, right, bottom)))

    win32gui.EnumWindows(callback, None)
    return found


def capture_bbox(bbox: tuple[int, int, int, int]) -> Any:
    from PIL import ImageGrab  # type: ignore

    return ImageGrab.grab(bbox=bbox, all_screens=True)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sessions": [], "last_daily_report_date": ""}
    try:
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict) or not isinstance(state.get("sessions", []), list):
            raise ValueError("invalid state shape")
        state.setdefault("sessions", [])
        state.setdefault("last_daily_report_date", "")
        return state
    except (OSError, ValueError, json.JSONDecodeError) as error:
        logging.error("Khong doc duoc state (%s); tao state moi.", error)
        return {"sessions": [], "last_daily_report_date": ""}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    temporary.replace(path)


def sessions_for_date(state: dict[str, Any], target: date) -> list[dict[str, Any]]:
    prefix = target.isoformat()
    return [session for session in state.get("sessions", []) if str(session.get("detected_at", "")).startswith(prefix)]


def format_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def daily_totals(state: dict[str, Any], target: date) -> tuple[int, Decimal, int]:
    sessions = sessions_for_date(state, target)
    total = sum((Decimal(str(item.get("amount_usd", "0"))) for item in sessions), Decimal("0"))
    diamonds = sum(int(item.get("diamond_count") or 0) for item in sessions)
    return len(sessions), total, diamonds


class TelegramClient:
    def __init__(self, token: str, chat_id: str, timeout: int = 30) -> None:
        if not token or not chat_id:
            raise ValueError("Thieu telegram_bot_token hoac telegram_chat_id trong config.")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.timeout = timeout

    def _decode(self, response: Any) -> dict[str, Any]:
        payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error: {payload}")
        return payload

    def send_message(self, text: str) -> None:
        body = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}/sendMessage", data=body, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self._decode(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram HTTP {error.code}: {detail}") from error

    def send_photo(self, image: Any, caption: str = "") -> None:
        stream = io.BytesIO()
        image.save(stream, format="JPEG", quality=88)
        boundary = f"----AutoDesktop{uuid.uuid4().hex}"
        chunks: list[bytes] = []

        def field(name: str, value: str) -> None:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        field("chat_id", self.chat_id)
        if caption:
            field("caption", caption)
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="photo"; filename="tiktok-live.jpg"\r\n',
                b"Content-Type: image/jpeg\r\n\r\n",
                stream.getvalue(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(
            f"{self.base_url}/sendPhoto",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            self._decode(response)


def new_session_message(result: LiveResult, state: dict[str, Any], now: datetime) -> str:
    count, total, diamonds = daily_totals(state, now.date())
    lines = [
        "📊 TIKTOK LIVE - PHIÊN MỚI KẾT THÚC",
        f"• Tạm tính phiên LIVE: ${format_money(result.amount)}",
    ]
    if result.diamond_count is not None:
        lines.append(f"• Kim cương: {result.diamond_count:,}")
    lines.extend(
        [
            f"• Ghi nhận lúc: {now:%H:%M:%S %d/%m/%Y}",
            "",
            f"Tổng hôm nay: {count} phiên | ${format_money(total)}",
        ]
    )
    if diamonds:
        lines[-1] += f" | {diamonds:,} kim cương"
    return "\n".join(lines)


def daily_message(state: dict[str, Any], target: date) -> str:
    count, total, diamonds = daily_totals(state, target)
    lines = [
        f"📅 TỔNG KẾT TIKTOK LIVE {target:%d/%m/%Y}",
        f"• Số phiên: {count}",
        f"• Tổng tạm tính: ${format_money(total)}",
    ]
    if diamonds:
        lines.append(f"• Tổng kim cương OCR: {diamonds:,}")
    return "\n".join(lines)


def register_result(
    result: LiveResult,
    state: dict[str, Any],
    state_path: Path,
    client: TelegramClient,
    config: dict[str, Any],
    now: datetime,
) -> bool:
    known = {str(item.get("signature")) for item in state.get("sessions", [])}
    if result.signature in known:
        return False

    entry = {
        "signature": result.signature,
        "amount_usd": format_money(result.amount),
        "diamond_count": result.diamond_count,
        "detected_at": now.isoformat(timespec="seconds"),
        "summary": result.summary,
    }
    state["sessions"].append(entry)
    # Tao message voi tong da bao gom phien vua phat hien, nhung chi ghi state sau khi gui thanh cong.
    try:
        client.send_message(new_session_message(result, state, now))
    except Exception:
        state["sessions"].pop()
        raise

    if bool(config.get("send_screenshot", False)):
        try:
            client.send_photo(result.screenshot, f"TikTok LIVE: ${format_money(result.amount)}")
        except Exception as error:
            # Text report da gui thanh cong; khong gui lai text chi vi upload anh loi.
            logging.warning("Gui anh chup Telegram that bai: %s", error)

    limit = max(20, int(config.get("history_limit", 500)))
    state["sessions"] = state["sessions"][-limit:]
    save_state(state_path, state)
    return True


def maybe_send_daily(state: dict[str, Any], state_path: Path, client: TelegramClient, config: dict[str, Any], now: datetime) -> bool:
    report_time = str(config.get("daily_report_time", "23:55"))
    try:
        hour, minute = (int(part) for part in report_time.split(":", maxsplit=1))
        scheduled_minutes = hour * 60 + minute
    except (TypeError, ValueError):
        raise ValueError("daily_report_time phai co dang HH:MM, vi du 23:55")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("daily_report_time khong hop le")
    if now.hour * 60 + now.minute < scheduled_minutes:
        return False
    today = now.date().isoformat()
    if state.get("last_daily_report_date") == today:
        return False
    count, _, _ = daily_totals(state, now.date())
    if count == 0 and not bool(config.get("send_empty_daily_report", False)):
        state["last_daily_report_date"] = today
        save_state(state_path, state)
        return False
    client.send_message(daily_message(state, now.date()))
    state["last_daily_report_date"] = today
    save_state(state_path, state)
    return True


def save_debug_image(image: Any, debug_dir: Path) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("screen-%Y%m%d-%H%M%S.jpg")
    image.save(debug_dir / name, quality=90)


def scan_once(config: dict[str, Any]) -> list[LiveResult]:
    windows = find_tiktok_windows(config.get("window_title_keywords", []))
    results: list[LiveResult] = []
    for _, title, bbox in windows:
        try:
            image = capture_bbox(bbox)
            if bool(config.get("debug_screenshots", False)):
                save_debug_image(image, runtime_dir() / "debug")
            result = analyze_image(image, config)
            if result:
                results.append(result)
        except Exception:
            logging.exception("Loi khi OCR cua so '%s'.", title)
    return results


STOP_REQUESTED = False


def request_stop(*_: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def run_daemon(config: dict[str, Any], state_path: Path, once: bool = False) -> int:
    client = TelegramClient(str(config.get("telegram_bot_token", "")), str(config.get("telegram_chat_id", "")))
    state = load_state(state_path)
    interval = max(5.0, float(config.get("scan_interval_seconds", 15)))
    last_no_window_log = 0.0
    screen_cache: dict[int, str] = {}
    logging.info("Bat dau theo doi TikTok LIVE Studio; chu ky %.1f giay.", interval)

    while not STOP_REQUESTED:
        now = datetime.now()
        try:
            windows = find_tiktok_windows(config.get("window_title_keywords", []))
            if not windows and time.monotonic() - last_no_window_log > 300:
                logging.info("Chua thay cua so TikTok LIVE Studio dang hien thi.")
                last_no_window_log = time.monotonic()
            for hwnd, title, bbox in windows:
                image = capture_bbox(bbox)
                change_key = screen_change_key(image)
                if screen_cache.get(hwnd) == change_key:
                    continue
                if bool(config.get("debug_screenshots", False)):
                    save_debug_image(image, runtime_dir() / "debug")
                result = analyze_image(image, config)
                screen_cache[hwnd] = change_key
                if result and register_result(result, state, state_path, client, config, now):
                    logging.info("Da gui Telegram: $%s tu '%s'.", format_money(result.amount), title)
            if maybe_send_daily(state, state_path, client, config, now):
                logging.info("Da gui bao cao tong ket ngay.")
        except Exception:
            logging.exception("Vong quet that bai; se thu lai.")
        if once:
            break
        # Sleep theo nhieu dot ngan de thoat nhanh khi Task Scheduler dung task.
        deadline = time.monotonic() + interval
        while not STOP_REQUESTED and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))
    logging.info("Da dung TikTok LIVE reporter.")
    return 0


def analyze_paths(paths: Iterable[Path], config: dict[str, Any]) -> int:
    from PIL import Image  # type: ignore

    found = 0
    for path in paths:
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
            result = analyze_image(image, config)
            payload = result.as_public_dict() if result else {"result": None}
            print(json.dumps({"file": str(path), **payload}, ensure_ascii=False))
            found += int(result is not None)
        except Exception as error:
            print(json.dumps({"file": str(path), "error": str(error)}, ensure_ascii=False))
    return 0 if found else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCR doanh thu TikTok LIVE Studio va gui Telegram")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--state", type=Path, default=runtime_dir() / "state.json")
    parser.add_argument("--log", type=Path, default=runtime_dir() / "live-reporter.log")
    parser.add_argument("--once", action="store_true", help="Quet man hinh mot lan roi thoat")
    parser.add_argument("--image", type=Path, help="Chi OCR mot anh, khong gui Telegram")
    parser.add_argument("--image-dir", type=Path, help="OCR tat ca anh JPG/PNG trong thu muc")
    parser.add_argument("--test-telegram", action="store_true", help="Gui tin nhan thu roi thoat")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log, args.verbose)
    try:
        config = load_config(args.config)
        configure_tesseract(config)
        if args.image:
            return analyze_paths([args.image], config)
        if args.image_dir:
            extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
            paths = sorted(path for path in args.image_dir.iterdir() if path.suffix.casefold() in extensions)
            return analyze_paths(paths, config)
        if args.test_telegram:
            client = TelegramClient(str(config.get("telegram_bot_token", "")), str(config.get("telegram_chat_id", "")))
            client.send_message(f"✅ Auto Desktop LIVE Reporter ket noi thanh cong luc {datetime.now():%H:%M:%S %d/%m/%Y}.")
            print("Telegram OK")
            return 0
        set_dpi_awareness()
        signal.signal(signal.SIGINT, request_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_stop)
        return run_daemon(config, args.state, once=args.once)
    except Exception as error:
        logging.exception("Khong the khoi dong: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
