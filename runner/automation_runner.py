#!/usr/bin/env python3

import pyautogui
import argparse
import ctypes
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime
from typing import Any
from typing import cast
from zoneinfo import ZoneInfo
import threading
import os

if sys.platform == "win32":
    import win32api
    import win32con

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}")


def normalize_text(value: str) -> str:
    return "".join(value.lower().split())


def prepare_ocr_variants(image: Any, threshold: int | None) -> list[Any]:
    try:
        from PIL import ImageOps  # type: ignore
    except ImportError:
        return [image]

    grayscale = ImageOps.grayscale(image)
    enhanced = ImageOps.autocontrast(grayscale)
    scaled = enhanced.resize((enhanced.width * 2, enhanced.height * 2))

    variants = [image, enhanced, scaled]
    if threshold is not None:
        binary = scaled.point(lambda pixel: 255 if pixel > threshold else 0)
        variants.append(binary)

    return variants


def extract_text_from_screen(
    *,
    region: list[int] | None,
    lang: str,
    tesseract_config: str,
    threshold: int | None,
) -> str:
    try:
        import pyautogui  # type: ignore
        import pytesseract  # type: ignore
    except ImportError as error:
        raise RuntimeError("pytesseract and pyautogui are required for OCR checks.") from error

    screenshot = pyautogui.screenshot(region=tuple(region) if region else None)
    extracted_results: list[str] = []
    for variant in prepare_ocr_variants(screenshot, threshold):
        extracted_results.append(
            pytesseract.image_to_string(variant, lang=lang, config=tesseract_config).strip()
        )

    extracted_results.sort(key=len, reverse=True)
    return extracted_results[0] if extracted_results else ""


def load_workflow(raw: str) -> dict[str, Any]:
    workflow = json.loads(raw)
    if "startSteps" not in workflow or not isinstance(workflow["startSteps"], list):
        raise ValueError("Workflow must contain a startSteps array.")
    if "stopSteps" not in workflow or not isinstance(workflow["stopSteps"], list):
        raise ValueError("Workflow must contain a stopSteps array.")
    return workflow


def run_command(command: str, dry_run: bool) -> None:
    if dry_run:
        log(f"DRY RUN launch: {command}")
        return
    subprocess.run(command, shell=True, check=True)


def to_screen_int(value: Any) -> int:
    return int(value)


def get_mouse_position(pyautogui: Any | None = None) -> tuple[int, int] | None:
    try:
        if pyautogui is None:
            import pyautogui as imported_pyautogui  # type: ignore

            pyautogui = imported_pyautogui
        position = pyautogui.position()
        return int(position.x), int(position.y)
    except Exception:
        return None


def get_darwin_accessibility_status() -> str:
    if sys.platform != "darwin":
        return "not-applicable"

    try:
        application_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        application_services.AXIsProcessTrusted.restype = ctypes.c_bool
        trusted = bool(application_services.AXIsProcessTrusted())
        return "trusted" if trusted else "not-trusted"
    except OSError:
        return "framework-unavailable"
    except Exception as error:
        return f"error:{error}"


def get_frontmost_app_name() -> str | None:
    if sys.platform != "darwin":
        return None

    script = 'tell application "System Events" to get name of first application process whose frontmost is true'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        app_name = result.stdout.strip()
        return app_name or None
    except Exception:
        return None


def safe_locate_on_screen(
    pyautogui: Any,
    image: str,
    *,
    confidence: float,
    region: list[int] | None = None,
) -> tuple[Any | None, str | None]:
    try:
        match = pyautogui.locateOnScreen(
            image,
            confidence=confidence,
            region=tuple(region) if region else None,
        )
        return match, None
    except Exception as error:
        error_name = type(error).__name__
        if error_name in {"ImageNotFoundException"}:
            return None, repr(error)
        raise


def should_repeat_after_focus_change(frontmost_before: str | None, frontmost_after: str | None) -> bool:
    if sys.platform != "darwin":
        return False
    if not frontmost_before or not frontmost_after:
        return False
    return frontmost_before != frontmost_after


def perform_darwin_click(x: int, y: int, click_count: int = 1, button: str = "left") -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "not-darwin"

    try:
        application_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
    except OSError:
        return False, "application-services-unavailable"

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    event_type_move = 5
    event_type_left_down = 1
    event_type_left_up = 2
    event_type_right_down = 3
    event_type_right_up = 4
    mouse_button_left = 0
    mouse_button_right = 1
    hid_event_tap = 0
    click_state_field = 1

    button_name = str(button).lower()
    if button_name == "right":
        down_event_type = event_type_right_down
        up_event_type = event_type_right_up
        mouse_button = mouse_button_right
    else:
        down_event_type = event_type_left_down
        up_event_type = event_type_left_up
        mouse_button = mouse_button_left

    application_services.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    application_services.CGEventCreateMouseEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        CGPoint,
        ctypes.c_uint32,
    ]
    application_services.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    application_services.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
    application_services.CFRelease.argtypes = [ctypes.c_void_p]

    point = CGPoint(float(x), float(y))
    move_event = application_services.CGEventCreateMouseEvent(None, event_type_move, point, mouse_button)
    if move_event:
        application_services.CGEventPost(hid_event_tap, move_event)
        application_services.CFRelease(move_event)
        time.sleep(0.01)

    for click_index in range(click_count):
        down_event = application_services.CGEventCreateMouseEvent(None, down_event_type, point, mouse_button)
        up_event = application_services.CGEventCreateMouseEvent(None, up_event_type, point, mouse_button)
        if not down_event or not up_event:
            if down_event:
                application_services.CFRelease(down_event)
            if up_event:
                application_services.CFRelease(up_event)
            return False, "event-create-failed"

        current_click_count = click_index + 1
        application_services.CGEventSetIntegerValueField(down_event, click_state_field, current_click_count)
        application_services.CGEventSetIntegerValueField(up_event, click_state_field, current_click_count)
        application_services.CGEventPost(hid_event_tap, down_event)
        time.sleep(0.07)
        application_services.CGEventPost(hid_event_tap, up_event)
        application_services.CFRelease(down_event)
        application_services.CFRelease(up_event)
        if click_index + 1 < click_count:
            time.sleep(0.12)

    return True, "quartz"

def perform_click(pyautogui, x, y, button="left"):
    screen_x = int(x)
    screen_y = int(y)

    if sys.platform == "win32":
        win32api.SetCursorPos((screen_x, screen_y))
        time.sleep(0.03)

        if button == "right":
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0)
            time.sleep(0.03)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0)
            backend = "pywin32"
        else:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
            time.sleep(0.03)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
            backend = "pywin32"

        return screen_x, screen_y, backend

    # macOS
    darwin_success, backend = perform_darwin_click(
        screen_x,
        screen_y,
        click_count=1,
        button=button,
    )

    if not darwin_success:
        pyautogui.click(x=screen_x, y=screen_y, button=button)
        backend = f"pyautogui:{backend}"

    return screen_x, screen_y, backend


def perform_double_click(
    pyautogui: Any,
    x: Any,
    y: Any,
    interval: float = 0.15,
    button: str = "left",
) -> tuple[int, int, str]:
    screen_x = to_screen_int(x)
    screen_y = to_screen_int(y)
    frontmost_before = get_frontmost_app_name()
    darwin_success, backend = perform_darwin_click(screen_x, screen_y, click_count=2, button=button)
    if not darwin_success:
        pyautogui.moveTo(screen_x, screen_y)
        pyautogui.mouseDown(x=screen_x, y=screen_y, button=button)
        time.sleep(0.07)
        pyautogui.mouseUp(x=screen_x, y=screen_y, button=button)
        time.sleep(interval)
        pyautogui.mouseDown(x=screen_x, y=screen_y, button=button)
        time.sleep(0.07)
        pyautogui.mouseUp(x=screen_x, y=screen_y, button=button)
        backend = f"pyautogui-fallback:{backend}"
    frontmost_after = get_frontmost_app_name()
    if should_repeat_after_focus_change(frontmost_before, frontmost_after):
        log(f"Focus changed during double click: {frontmost_before} -> {frontmost_after}. Repeating double click at same point.")
        time.sleep(0.2)
        retry_success, retry_backend = perform_darwin_click(screen_x, screen_y, click_count=2, button=button)
        if not retry_success:
            pyautogui.moveTo(screen_x, screen_y)
            pyautogui.mouseDown(x=screen_x, y=screen_y, button=button)
            time.sleep(0.07)
            pyautogui.mouseUp(x=screen_x, y=screen_y, button=button)
            time.sleep(interval)
            pyautogui.mouseDown(x=screen_x, y=screen_y, button=button)
            time.sleep(0.07)
            pyautogui.mouseUp(x=screen_x, y=screen_y, button=button)
            retry_backend = f"pyautogui-fallback:{retry_backend}"
        backend = f"{backend}+focus-retry:{retry_backend}"
    return screen_x, screen_y, backend


def highlight_coordinate(x: int, y: int, duration_ms: int = 500) -> None:
    try:
        import tkinter as tk
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        
        size = 40
        left = int(x - size / 2)
        top = int(y - size / 2)
        root.geometry(f"{size}x{size}+{left}+{top}")
        
        canvas = tk.Canvas(root, width=size, height=size, highlightthickness=0)
        canvas.pack()
        
        if sys.platform == "win32":
            root.wm_attributes("-transparentcolor", "white")
            canvas.configure(bg="white")
        else:
            root.attributes("-alpha", 0.85)
            canvas.configure(bg="red")
            
        canvas.create_oval(2, 2, size-2, size-2, outline="red", width=3)
        canvas.create_line(size/2, 0, size/2, size, fill="red", width=2)
        canvas.create_line(0, size/2, size, size/2, fill="red", width=2)
        
        root.after(duration_ms, root.destroy)
        root.mainloop()
    except Exception as e:
        log(f"Highlight coordinate failed (non-critical): {e}")


def locate_text_in_image(img, target_text: str) -> tuple[int, int, int, int] | None:
    try:
        from pytesseract import Output
        import pytesseract
        
        data = pytesseract.image_to_data(img, output_type=Output.DICT)
        n_boxes = len(data['text'])
        
        target_words = target_text.lower().split()
        if not target_words:
            return None
            
        ocr_words = []
        for i in range(n_boxes):
            text = data['text'][i].strip()
            conf = float(data['conf'][i]) if 'conf' in data else 100
            if text and conf > -1:
                ocr_words.append({
                    'text': text.lower(),
                    'left': data['left'][i],
                    'top': data['top'][i],
                    'width': data['width'][i],
                    'height': data['height'][i],
                    'index': i
                })
                
        m = len(target_words)
        for i in range(len(ocr_words) - m + 1):
            match = True
            for j in range(m):
                if target_words[j] not in ocr_words[i+j]['text']:
                    match = False
                    break
            if match:
                first_word = ocr_words[i]
                last_word = ocr_words[i + m - 1]
                
                left = first_word['left']
                top = min(w['top'] for w in ocr_words[i:i+m])
                right = last_word['left'] + last_word['width']
                bottom = max(w['top'] + w['height'] for w in ocr_words[i:i+m])
                
                width = right - left
                height = bottom - top
                return (left, top, width, height)
    except Exception as e:
        log(f"OCR text search in image failed: {e}")
    return None


def step_click(step: dict[str, Any], dry_run: bool) -> None:
    delay_before = float(step.get("delayBeforeSec", 0))
    if delay_before > 0:
        log(f"Waiting {delay_before}s before click...")
        time.sleep(delay_before)

    click_type = step.get("clickType", "coordinate")
    if click_type == "image":
        image = step.get("image")
        if not image:
            raise ValueError("Image path is required for click by image.")
        timeout = step.get("timeoutMs", 5000)
        confidence = step.get("confidence", 0.8)
        region = step.get("region")

        if dry_run:
            log(f"DRY RUN click by image image={image} timeoutMs={timeout} confidence={confidence} region={region}")
        else:
            try:
                import pyautogui  # type: ignore
            except ImportError as error:
                raise RuntimeError("pyautogui is required for image detection and clicking.") from error

            log(
                "Click diagnostics "
                f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                f"frontmostApp={get_frontmost_app_name()} region={region} confidence={confidence}"
            )
            start = time.time()
            found = False
            last_locate_error: str | None = None
            while time.time() - start < timeout / 1000:
                match, locate_error = safe_locate_on_screen(pyautogui, image, confidence=confidence, region=region)
                if locate_error:
                    last_locate_error = locate_error
                if match:
                    center_point = pyautogui.center(match)
                    mouse_before = get_mouse_position(pyautogui)
                    frontmost_before = get_frontmost_app_name()
                    log(
                        f"Found image match={match} center=({int(center_point.x)}, {int(center_point.y)}) "
                        f"mouseBefore={mouse_before} frontmostBefore={frontmost_before}"
                    )
                    screen_x, screen_y, backend = perform_click(pyautogui, center_point.x, center_point.y)
                    mouse_after = get_mouse_position(pyautogui)
                    frontmost_after = get_frontmost_app_name()
                    log(
                        f"Found image and clicked at ({screen_x}, {screen_y}) "
                        f"backend={backend} mouseAfter={mouse_after} frontmostAfter={frontmost_after}"
                    )
                    found = True
                    break
                time.sleep(0.4)

            if not found:
                if last_locate_error:
                    raise TimeoutError(f"Image for clicking not found within timeout: {image}. Last locate error: {last_locate_error}")
                raise TimeoutError(f"Image for clicking not found within timeout: {image}")
    elif click_type == "text":
        text_val = step.get("text")
        if not text_val:
            raise ValueError("Text is required for click by text.")
        timeout = step.get("timeoutMs", 5000)
        region = step.get("region")

        if dry_run:
            log(f"DRY RUN click by text text='{text_val}' timeoutMs={timeout} region={region}")
        else:
            try:
                import pyautogui  # type: ignore
                import pytesseract  # type: ignore
            except ImportError as error:
                raise RuntimeError("pyautogui and pytesseract are required for text detection and clicking.") from error

            log(
                "Click text diagnostics "
                f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                f"frontmostApp={get_frontmost_app_name()} region={region} text='{text_val}'"
            )
            start = time.time()
            found = False
            while time.time() - start < timeout / 1000:
                with gui_lock:
                    screenshot = pyautogui.screenshot(region=tuple(region) if region else None)
                
                match_box = locate_text_in_image(screenshot, text_val)
                if match_box:
                    left, top, width, height = match_box
                    offset_x = region[0] if region else 0
                    offset_y = region[1] if region else 0
                    
                    center_x = offset_x + left + width // 2
                    center_y = offset_y + top + height // 2
                    
                    highlight_coordinate(center_x, center_y)
                    
                    mouse_before = get_mouse_position(pyautogui)
                    frontmost_before = get_frontmost_app_name()
                    log(
                        f"Found text match box={match_box} globalCenter=({center_x}, {center_y}) "
                        f"mouseBefore={mouse_before} frontmostBefore={frontmost_before}"
                    )
                    screen_x, screen_y, backend = perform_click(pyautogui, center_x, center_y)
                    mouse_after = get_mouse_position(pyautogui)
                    frontmost_after = get_frontmost_app_name()
                    log(
                        f"Found text and clicked at ({screen_x}, {screen_y}) "
                        f"backend={backend} mouseAfter={mouse_after} frontmostAfter={frontmost_after}"
                    )
                    found = True
                    break
                time.sleep(0.4)

            if not found:
                raise TimeoutError(f"Text for clicking not found within timeout: '{text_val}'")
    else:
        x = step.get("x")
        y = step.get("y")
        if x is None or y is None:
            raise ValueError("Coordinates x and y are required for click by coordinate.")
        if dry_run:
            log(f"DRY RUN click at ({x}, {y})")
        else:
            try:
                import pyautogui  # type: ignore
            except ImportError as error:
                raise RuntimeError("pyautogui is required for real click actions.") from error

            highlight_coordinate(x, y)

            mouse_before = get_mouse_position(pyautogui)
            log(
                "Click diagnostics "
                f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                f"frontmostApp={get_frontmost_app_name()} target=({int(x)}, {int(y)}) mouseBefore={mouse_before}"
            )
            screen_x, screen_y, backend = perform_click(pyautogui, x, y)
            mouse_after = get_mouse_position(pyautogui)
            log(
                f"Clicked at ({screen_x}, {screen_y}) backend={backend} "
                f"mouseAfter={mouse_after} frontmostAfter={get_frontmost_app_name()}"
            )

    delay_after = float(step.get("delayAfterSec", 0))
    if delay_after > 0:
        log(f"Waiting {delay_after}s after click...")
        time.sleep(delay_after)


def step_double_click(step: dict[str, Any], dry_run: bool) -> None:
    delay_before = float(step.get("delayBeforeSec", 0))
    if delay_before > 0:
        log(f"Waiting {delay_before}s before double click...")
        time.sleep(delay_before)

    click_type = step.get("clickType", "coordinate")
    interval = step.get("intervalSec", 0.15)
    if click_type == "image":
        image = step.get("image")
        if not image:
            raise ValueError("Image path is required for double click by image.")
        timeout = step.get("timeoutMs", 5000)
        confidence = step.get("confidence", 0.8)
        region = step.get("region")

        if dry_run:
            log(f"DRY RUN double click by image image={image} timeoutMs={timeout} confidence={confidence} region={region}")
        else:
            try:
                import pyautogui  # type: ignore
            except ImportError as error:
                raise RuntimeError("pyautogui is required for image detection and clicking.") from error

            log(
                "Double click diagnostics "
                f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                f"frontmostApp={get_frontmost_app_name()} region={region} confidence={confidence} interval={interval}"
            )
            start = time.time()
            found = False
            last_locate_error: str | None = None
            while time.time() - start < timeout / 1000:
                match, locate_error = safe_locate_on_screen(pyautogui, image, confidence=confidence, region=region)
                if locate_error:
                    last_locate_error = locate_error
                if match:
                    center_point = pyautogui.center(match)
                    mouse_before = get_mouse_position(pyautogui)
                    frontmost_before = get_frontmost_app_name()
                    log(
                        f"Found image match={match} center=({int(center_point.x)}, {int(center_point.y)}) "
                        f"mouseBefore={mouse_before} frontmostBefore={frontmost_before}"
                    )
                    screen_x, screen_y, backend = perform_double_click(pyautogui, center_point.x, center_point.y, interval=interval)
                    mouse_after = get_mouse_position(pyautogui)
                    frontmost_after = get_frontmost_app_name()
                    log(
                        f"Found image and double clicked at ({screen_x}, {screen_y}) "
                        f"backend={backend} mouseAfter={mouse_after} frontmostAfter={frontmost_after}"
                    )
                    found = True
                    break
                time.sleep(0.4)

            if not found:
                if last_locate_error:
                    raise TimeoutError(f"Image for double clicking not found within timeout: {image}. Last locate error: {last_locate_error}")
                raise TimeoutError(f"Image for double clicking not found within timeout: {image}")
    elif click_type == "text":
        text_val = step.get("text")
        if not text_val:
            raise ValueError("Text is required for double click by text.")
        timeout = step.get("timeoutMs", 5000)
        region = step.get("region")

        if dry_run:
            log(f"DRY RUN double click by text text='{text_val}' timeoutMs={timeout} region={region}")
        else:
            try:
                import pyautogui  # type: ignore
                import pytesseract  # type: ignore
            except ImportError as error:
                raise RuntimeError("pyautogui and pytesseract are required for text detection and double clicking.") from error

            log(
                "Double click text diagnostics "
                f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                f"frontmostApp={get_frontmost_app_name()} region={region} text='{text_val}' interval={interval}"
            )
            start = time.time()
            found = False
            while time.time() - start < timeout / 1000:
                with gui_lock:
                    screenshot = pyautogui.screenshot(region=tuple(region) if region else None)
                
                match_box = locate_text_in_image(screenshot, text_val)
                if match_box:
                    left, top, width, height = match_box
                    offset_x = region[0] if region else 0
                    offset_y = region[1] if region else 0
                    
                    center_x = offset_x + left + width // 2
                    center_y = offset_y + top + height // 2
                    
                    highlight_coordinate(center_x, center_y)
                    
                    mouse_before = get_mouse_position(pyautogui)
                    frontmost_before = get_frontmost_app_name()
                    log(
                        f"Found text match box={match_box} globalCenter=({center_x}, {center_y}) "
                        f"mouseBefore={mouse_before} frontmostBefore={frontmost_before}"
                    )
                    screen_x, screen_y, backend = perform_double_click(pyautogui, center_x, center_y, interval=interval)
                    mouse_after = get_mouse_position(pyautogui)
                    frontmost_after = get_frontmost_app_name()
                    log(
                        f"Found text and double clicked at ({screen_x}, {screen_y}) "
                        f"backend={backend} mouseAfter={mouse_after} frontmostAfter={frontmost_after}"
                    )
                    found = True
                    break
                time.sleep(0.4)

            if not found:
                raise TimeoutError(f"Text for double clicking not found within timeout: '{text_val}'")
    else:
        x = step.get("x")
        y = step.get("y")
        if x is None or y is None:
            raise ValueError("Coordinates x and y are required for double click by coordinate.")
        if dry_run:
            log(f"DRY RUN double click at ({x}, {y})")
        else:
            try:
                import pyautogui  # type: ignore
            except ImportError as error:
                raise RuntimeError("pyautogui is required for real click actions.") from error

            highlight_coordinate(x, y)

            mouse_before = get_mouse_position(pyautogui)
            log(
                "Double click diagnostics "
                f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                f"frontmostApp={get_frontmost_app_name()} target=({int(x)}, {int(y)}) interval={interval} mouseBefore={mouse_before}"
            )
            screen_x, screen_y, backend = perform_double_click(pyautogui, x, y, interval=interval)
            mouse_after = get_mouse_position(pyautogui)
            log(
                f"Double clicked at ({screen_x}, {screen_y}) backend={backend} "
                f"mouseAfter={mouse_after} frontmostAfter={get_frontmost_app_name()}"
            )

    delay_after = float(step.get("delayAfterSec", 0))
    if delay_after > 0:
        log(f"Waiting {delay_after}s after double click...")
        time.sleep(delay_after)


def step_wait(step: dict[str, Any]) -> None:
    ms = step["ms"]
    log(f"Waiting {ms} ms")
    time.sleep(ms / 1000)


def step_wait_for_image(step: dict[str, Any], dry_run: bool) -> None:
    image = step["image"]
    timeout = step.get("timeoutMs", 5000)
    confidence = step.get("confidence", 0.8)
    region = step.get("region")

    if dry_run:
        log(f"DRY RUN wait_for_image image={image} timeoutMs={timeout} confidence={confidence} region={region}")
        return

    try:
        import pyautogui  # type: ignore
    except ImportError as error:
        raise RuntimeError("pyautogui is required for image detection.") from error

    start = time.time()
    last_locate_error: str | None = None
    while time.time() - start < timeout / 1000:
        match, locate_error = safe_locate_on_screen(pyautogui, image, confidence=confidence, region=region)
        if locate_error:
            last_locate_error = locate_error
        if match:
            log(f"Found image {image}")
            return
        time.sleep(0.4)

    if last_locate_error:
        raise TimeoutError(f"Image not found within timeout: {image}. Last locate error: {last_locate_error}")
    raise TimeoutError(f"Image not found within timeout: {image}")


def step_check_text(step: dict[str, Any], dry_run: bool) -> None:
    text = step["text"]
    timeout = step.get("timeoutMs", 5000)
    region = step.get("region")
    lang = step.get("lang", "eng")
    tesseract_config = step.get("tesseractConfig", "--psm 6")
    threshold = step.get("ocrThreshold")
    normalized_target = normalize_text(text)

    if dry_run:
        log(
            "DRY RUN check_text "
            f"text={text} timeoutMs={timeout} region={region} lang={lang} config={tesseract_config}"
        )
        return

    start = time.time()
    last_extracted = ""
    while time.time() - start < timeout / 1000:
        extracted = extract_text_from_screen(
            region=region,
            lang=lang,
            tesseract_config=tesseract_config,
            threshold=threshold,
        )
        last_extracted = extracted
        normalized_extracted = normalize_text(extracted)

        if text.lower() in extracted.lower() or normalized_target in normalized_extracted:
            log(f"Found text '{text}'")
            return
        time.sleep(0.5)

    condensed = " ".join(last_extracted.split())
    raise TimeoutError(f"Text not found within timeout: {text}. OCR saw: '{condensed[:180]}'")


def step_conditional(step: dict[str, Any], dry_run: bool) -> None:
    condition_type = step.get("conditionType", "image")
    region = step.get("region")
    condition_met = False

    if condition_type == "image":
        image = step.get("image")
        confidence = step.get("confidence", 0.8)
        if not image:
            log("Condition check skipped: No image path provided")
            return
        
        if dry_run:
            log(f"DRY RUN condition check for image: {image} confidence={confidence}")
            condition_met = True
        else:
            try:
                import pyautogui
                match, _ = safe_locate_on_screen(pyautogui, image, confidence=confidence, region=region)
                condition_met = match is not None
            except Exception as err:
                log(f"Error checking condition image: {err}")
    else:
        text = step.get("text")
        if not text:
            log("Condition check skipped: No check text provided")
            return
        
        if dry_run:
            log(f"DRY RUN condition check for text: '{text}'")
            condition_met = True
        else:
            try:
                import pyautogui
                import pytesseract
                screenshot = pyautogui.screenshot(region=tuple(region) if region else None)
                extracted = pytesseract.image_to_string(screenshot)
                condition_met = text.lower() in extracted.lower()
            except Exception as err:
                log(f"Error checking condition text: {err}")

    if condition_met:
        log(f"Condition MET. Executing action: {step.get('actionType')}")
        action_type = step.get("actionType")
        if action_type == "click":
            x = step.get("clickX")
            y = step.get("clickY")
            if x is None or y is None:
                log("Error: clickX or clickY is missing")
                return
            if dry_run:
                log(f"DRY RUN click at ({x}, {y})")
            else:
                import pyautogui
                highlight_coordinate(x, y)
                mouse_before = get_mouse_position(pyautogui)
                log(
                    "Conditional click diagnostics "
                    f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                    f"target=({int(x)}, {int(y)}) mouseBefore={mouse_before}"
                )
                screen_x, screen_y, backend = perform_click(pyautogui, x, y)
                mouse_after = get_mouse_position(pyautogui)
                log(f"Clicked at ({screen_x}, {screen_y}) backend={backend} mouseAfter={mouse_after}")
        elif action_type == "double_click":
            x = step.get("clickX")
            y = step.get("clickY")
            interval = step.get("intervalSec", 0.15)
            if x is None or y is None:
                log("Error: clickX or clickY is missing")
                return
            if dry_run:
                log(f"DRY RUN double click at ({x}, {y})")
            else:
                import pyautogui
                highlight_coordinate(x, y)
                mouse_before = get_mouse_position(pyautogui)
                log(
                    "Conditional double click diagnostics "
                    f"platform={sys.platform} accessibility={get_darwin_accessibility_status()} "
                    f"target=({int(x)}, {int(y)}) interval={interval} mouseBefore={mouse_before}"
                )
                screen_x, screen_y, backend = perform_double_click(pyautogui, x, y, interval=interval)
                mouse_after = get_mouse_position(pyautogui)
                log(f"Double clicked at ({screen_x}, {screen_y}) backend={backend} mouseAfter={mouse_after}")
        elif action_type == "click_image":
            click_image = step.get("clickImage")
            click_confidence = step.get("clickConfidence", 0.8)
            if not click_image:
                log("Error: clickImage path is missing")
                return
            if dry_run:
                log(f"DRY RUN click_image: {click_image} confidence={click_confidence}")
            else:
                import pyautogui
                match, _ = safe_locate_on_screen(pyautogui, click_image, confidence=click_confidence)
                if match:
                    center_point = pyautogui.center(match)
                    mouse_before = get_mouse_position(pyautogui)
                    log(
                        f"Conditional click_image match={match} center=({int(center_point.x)}, {int(center_point.y)}) "
                        f"mouseBefore={mouse_before} accessibility={get_darwin_accessibility_status()}"
                    )
                    screen_x, screen_y, backend = perform_click(pyautogui, center_point.x, center_point.y)
                    mouse_after = get_mouse_position(pyautogui)
                    log(
                        f"Found and clicked image at ({screen_x}, {screen_y}) "
                        f"backend={backend} mouseAfter={mouse_after}"
                    )
                else:
                    log(f"Target click image not found: {click_image}")
        elif action_type == "double_click_image":
            click_image = step.get("clickImage")
            click_confidence = step.get("clickConfidence", 0.8)
            if not click_image:
                log("Error: clickImage path is missing")
                return
            if dry_run:
                log(f"DRY RUN double_click_image: {click_image} confidence={click_confidence}")
            else:
                import pyautogui
                match, _ = safe_locate_on_screen(pyautogui, click_image, confidence=click_confidence)
                if match:
                    center_point = pyautogui.center(match)
                    mouse_before = get_mouse_position(pyautogui)
                    log(
                        f"Conditional double_click_image match={match} center=({int(center_point.x)}, {int(center_point.y)}) "
                        f"mouseBefore={mouse_before} accessibility={get_darwin_accessibility_status()}"
                    )
                    screen_x, screen_y, backend = perform_double_click(
                        pyautogui,
                        center_point.x,
                        center_point.y,
                        interval=step.get("intervalSec", 0.15),
                    )
                    mouse_after = get_mouse_position(pyautogui)
                    log(
                        f"Found and double clicked image at ({screen_x}, {screen_y}) "
                        f"backend={backend} mouseAfter={mouse_after}"
                    )
                else:
                    log(f"Target double click image not found: {click_image}")
        elif action_type == "launch_app":
            command = step.get("command")
            if not command:
                log("Error: launch command is missing")
                return
            if dry_run:
                log(f"DRY RUN launch: {command}")
            else:
                import subprocess
                subprocess.run(command, shell=True, check=True)
                log(f"Launched application command: {command}")
        elif action_type == "wait":
            wait_ms = step.get("waitMs", 1000)
            log(f"Waiting {wait_ms} ms")
            time.sleep(wait_ms / 1000)
    else:
        log("Condition NOT met. Skipping action.")


gui_lock = threading.RLock()
active_intervals = {}
intervals_lock = threading.Lock()

def resolve_workflow_path(path_str: str) -> str:
    if not path_str:
        return ""
    if os.path.isabs(path_str):
        return path_str
        
    # Check relative to cwd
    if os.path.exists(path_str):
        return os.path.abspath(path_str)
        
    # Check relative to workflows subdirectory inside cwd
    rel_workflows = os.path.join("workflows", path_str)
    if os.path.exists(rel_workflows):
        return os.path.abspath(rel_workflows)
        
    # Check relative to standard AppData directory
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        if app_data:
            standard_path = os.path.join(app_data, "auto-desktop", "workflows", path_str)
            if os.path.exists(standard_path):
                return standard_path
    elif sys.platform == "darwin":
        standard_path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "auto-desktop", "workflows", path_str)
        if os.path.exists(standard_path):
            return standard_path
            
    # Fallback to absolute path
    return os.path.abspath(path_str)

def step_run_workflow(step: dict[str, Any], dry_run: bool, depth: int) -> None:
    workflow_path = resolve_workflow_path(step.get("workflowPath", ""))
    if not workflow_path:
        log("No workflowPath specified. Skipping.")
        return
        
    if depth > 10:
        raise RuntimeError(f"Max workflow nesting depth (10) exceeded at {workflow_path}")
        
    log(f"Executing sub-workflow: {workflow_path}")
    if not os.path.exists(workflow_path):
        raise FileNotFoundError(f"Sub-workflow file not found: {workflow_path}")
        
    with open(workflow_path, "r", encoding="utf-8") as f:
        sub_wf = json.load(f)
        
    sub_settings = sub_wf.get("settings", {})
    sub_dry_run = dry_run
    sub_step_delay = float(sub_settings.get("stepDelaySec", 0))
    
    sub_start_steps = sub_wf.get("startSteps", [])
    sub_stop_steps = sub_wf.get("stopSteps", [])
    
    execute_step_list(sub_start_steps, sub_dry_run, f"sub-flow start ({os.path.basename(workflow_path)})", sub_step_delay, depth + 1)
    execute_step_list(sub_stop_steps, sub_dry_run, f"sub-flow stop ({os.path.basename(workflow_path)})", sub_step_delay, depth + 1)

def step_conditional_workflow(step: dict[str, Any], dry_run: bool, depth: int) -> None:
    condition_type = step.get("conditionType", "image")
    region = step.get("region")
    condition_met = False

    if condition_type == "image":
        image = step.get("image")
        confidence = step.get("confidence", 0.8)
        if not image:
            log("Condition check skipped: No image path provided")
            return
        
        if dry_run:
            log(f"DRY RUN condition check for image: {image} confidence={confidence}")
            condition_met = True
        else:
            try:
                import pyautogui
                with gui_lock:
                    match, _ = safe_locate_on_screen(pyautogui, image, confidence=confidence, region=region)
                condition_met = match is not None
            except Exception as err:
                log(f"Error checking condition image: {err}")
    else:
        text = step.get("text")
        if not text:
            log("Condition check skipped: No check text provided")
            return
        
        if dry_run:
            log(f"DRY RUN condition check for text: '{text}'")
            condition_met = True
        else:
            try:
                import pyautogui
                import pytesseract
                with gui_lock:
                    screenshot = pyautogui.screenshot(region=tuple(region) if region else None)
                extracted = pytesseract.image_to_string(screenshot)
                condition_met = text.lower() in extracted.lower()
            except Exception as err:
                log(f"Error checking condition text: {err}")

    if condition_met:
        then_path = step.get("thenWorkflowPath")
        if then_path:
            then_resolved = resolve_workflow_path(then_path)
            log(f"Condition MET. Running THEN workflow: {then_resolved}")
            step_run_workflow({"workflowPath": then_resolved}, dry_run, depth)
        else:
            log("Condition MET, but no thenWorkflowPath specified.")
    else:
        else_path = step.get("elseWorkflowPath")
        if else_path:
            else_resolved = resolve_workflow_path(else_path)
            log(f"Condition NOT met. Running ELSE workflow: {else_resolved}")
            step_run_workflow({"workflowPath": else_resolved}, dry_run, depth)
        else:
            log("Condition NOT met, and no elseWorkflowPath specified. Skipping.")

def step_check_interval(step: dict[str, Any], dry_run: bool) -> None:
    interval_id = step.get("intervalId")
    if not interval_id:
        log("No intervalId specified. Skipping check_interval step.")
        return
        
    with intervals_lock:
        if interval_id in active_intervals:
            log(f"Interval {interval_id} is already running. Stopping it first.")
            active_intervals[interval_id]["stop_event"].set()
            time.sleep(0.5)

        stop_event = threading.Event()
        t = threading.Thread(
            target=interval_worker,
            args=(interval_id, step, dry_run, stop_event),
            daemon=True
        )
        active_intervals[interval_id] = {
            "thread": t,
            "stop_event": stop_event
        }
        t.start()

def interval_worker(interval_id: str, step: dict[str, Any], dry_run: bool, stop_event: threading.Event) -> None:
    interval_sec = float(step.get("intervalSec", 5))
    action_workflow_path = resolve_workflow_path(step.get("actionWorkflowPath", "")) if step.get("actionWorkflowPath") else None
    
    stop_cond_type = step.get("stopConditionType")
    stop_image = step.get("stopImage")
    stop_confidence = float(step.get("stopConfidence", 0.8))
    stop_text = step.get("stopText")
    stop_region = step.get("stopRegion")
    
    log(f"[Interval {interval_id}] Worker thread started. Interval: {interval_sec}s")
    
    while not stop_event.is_set():
        condition_met = False
        if stop_cond_type == "image" and stop_image:
            if dry_run:
                log(f"[Interval {interval_id}] DRY RUN stop condition check for image: {stop_image}")
                condition_met = True
            else:
                try:
                    import pyautogui
                    with gui_lock:
                        match, _ = safe_locate_on_screen(pyautogui, stop_image, confidence=stop_confidence, region=stop_region)
                    condition_met = match is not None
                except Exception as err:
                    log(f"[Interval {interval_id}] Error checking stop image: {err}")
        elif stop_cond_type == "text" and stop_text:
            if dry_run:
                log(f"[Interval {interval_id}] DRY RUN stop condition check for text: '{stop_text}'")
                condition_met = True
            else:
                try:
                    import pyautogui
                    import pytesseract
                    with gui_lock:
                        screenshot = pyautogui.screenshot(region=tuple(stop_region) if stop_region else None)
                    extracted = pytesseract.image_to_string(screenshot)
                    condition_met = stop_text.lower() in extracted.lower()
                except Exception as err:
                    log(f"[Interval {interval_id}] Error checking stop text: {err}")
                
        if condition_met:
            log(f"[Interval {interval_id}] Stop condition met ({stop_cond_type}). Clearing interval.")
            break
            
        if action_workflow_path:
            log(f"[Interval {interval_id}] Triggering sub-workflow: {action_workflow_path}")
            try:
                if os.path.exists(action_workflow_path):
                    step_run_workflow({"workflowPath": action_workflow_path}, dry_run, depth=0)
                else:
                    log(f"[Interval {interval_id}] Action workflow path does not exist: {action_workflow_path}")
            except Exception as err:
                log(f"[Interval {interval_id}] Error executing action workflow: {err}")
                
        sleep_start = time.time()
        while time.time() - sleep_start < interval_sec:
            if stop_event.is_set():
                break
            time.sleep(0.1)
            
    with intervals_lock:
        if interval_id in active_intervals:
            del active_intervals[interval_id]
    log(f"[Interval {interval_id}] Worker thread stopped.")

def step_clear_interval(step: dict[str, Any]) -> None:
    interval_id = step.get("intervalId")
    if not interval_id:
        log("No intervalId specified for clear_interval step.")
        return
        
    with intervals_lock:
        if interval_id == "all":
            log("Stopping all active intervals...")
            for key, val in list(active_intervals.items()):
                val["stop_event"].set()
        elif interval_id in active_intervals:
            log(f"Stopping interval: {interval_id}")
            active_intervals[interval_id]["stop_event"].set()
        else:
            log(f"Interval {interval_id} not found or already stopped.")

def execute_step_list(steps: list[dict[str, Any]], dry_run: bool, label: str, step_delay: float = 0.0, depth: int = 0) -> None:
    log(f"Running {label} sequence with {len(steps)} step(s)")
    for index, step in enumerate(steps, start=1):
        step_type = step["type"]
        log(f"Step {index}/{len(steps)}: {step.get('name', step_type)} [{step_type}]")

        if step_type == "launch_app":
            run_command(step["command"], dry_run)
        elif step_type == "click":
            with gui_lock:
                step_click(step, dry_run)
        elif step_type == "double_click":
            with gui_lock:
                step_double_click(step, dry_run)
        elif step_type == "wait":
            step_wait(step)
        elif step_type == "wait_for_image":
            with gui_lock:
                step_wait_for_image(step, dry_run)
        elif step_type == "check_text":
            with gui_lock:
                step_check_text(step, dry_run)
        elif step_type == "conditional":
            with gui_lock:
                step_conditional(step, dry_run)
        elif step_type == "run_workflow":
            step_run_workflow(step, dry_run, depth)
        elif step_type == "conditional_workflow":
            step_conditional_workflow(step, dry_run, depth)
        elif step_type == "check_interval":
            step_check_interval(step, dry_run)
        elif step_type == "clear_interval":
            step_clear_interval(step)
        elif step_type == "press_key":
            with gui_lock:
                step_press_key(step, dry_run)
        else:
            raise ValueError(f"Unsupported step type: {step_type}")

        if step_delay > 0 and index < len(steps):
            log(f"Waiting {step_delay}s between steps...")
            time.sleep(step_delay)

def step_press_key(step: dict[str, Any], dry_run: bool) -> None:
    key = step.get("key", "f5").lower()
    if dry_run:
        log(f"DRY RUN press key: {key}")
    else:
        try:
            import pyautogui
            log(f"Pressing key: {key}")
            pyautogui.press(key)
        except Exception as err:
            log(f"Error pressing key {key}: {err}")
            raise



def wait_until_schedule(workflow: dict[str, Any], dry_run: bool) -> None:
    schedule = workflow.get("schedule", {})
    if not schedule.get("enabled"):
        return

    timezone = schedule.get("timezone", "UTC")
    start_at = schedule.get("startAt")
    if not start_at:
        return

    try:
        zone = ZoneInfo(timezone)
    except Exception:
        zone = ZoneInfo("UTC")

    now = datetime.now(zone)
    start_dt = datetime.fromisoformat(start_at)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=zone)

    seconds = (start_dt - now).total_seconds()
    if seconds <= 0:
        log("Schedule start time already reached, starting now")
        return

    if dry_run:
        log(f"DRY RUN schedule wait skipped ({int(seconds)} seconds until start)")
        return

    log(f"Waiting until scheduled start for {int(seconds)} second(s)")
    time.sleep(seconds)


def execute_workflow(workflow: dict[str, Any]) -> None:
    settings = workflow.get("settings", {})
    dry_run = settings.get("dryRun", True)
    step_delay = float(settings.get("stepDelaySec", 0))
    start_steps = cast(list[dict[str, Any]], workflow["startSteps"])
    stop_steps = cast(list[dict[str, Any]], workflow["stopSteps"])

    log(f"Starting workflow '{workflow.get('name', 'untitled')}'")
    log(f"Mode: {'dry-run' if dry_run else 'live'}")
    wait_until_schedule(workflow, dry_run)

    try:
        repeat = settings.get("repeat", {})
        if repeat.get("enabled"):
            times = repeat.get("times", 0)  # 0 means infinite loop
            interval_ms = repeat.get("intervalMs", 0)
            
            run_count = 0
            while True:
                run_count += 1
                log(f"--- Running workflow iteration {run_count} ---")
                execute_step_list(start_steps, dry_run, "start", step_delay)
                execute_step_list(stop_steps, dry_run, "stop", step_delay)
                
                if times > 0 and run_count >= times:
                    log(f"Reached loop count limit ({times}). Ending workflow.")
                    break
                
                log(f"Waiting {interval_ms} ms before next iteration...")
                time.sleep(interval_ms / 1000)
        else:
            execute_step_list(start_steps, dry_run, "start", step_delay)
            execute_step_list(stop_steps, dry_run, "stop", step_delay)

        log("Workflow finished successfully")
    finally:
        # Stop all running intervals
        with intervals_lock:
            if active_intervals:
                log("Cleaning up active intervals...")
                for id_key, item in list(active_intervals.items()):
                    item["stop_event"].set()
                active_intervals.clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-json", required=True, help="Raw workflow JSON string")
    args = parser.parse_args()

    workflow = load_workflow(args.workflow_json)
    execute_workflow(workflow)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f"ERROR: {error!r}")
        for line in traceback.format_exc().strip().splitlines():
            log(f"TRACE: {line}")
        raise
