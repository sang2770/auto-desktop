#!/usr/bin/env python3

import pyautogui
import argparse
import ctypes
import json
import subprocess
import sys
import time
import traceback
import io
import base64
from datetime import datetime
from typing import Any
from typing import cast
from zoneinfo import ZoneInfo
import threading
import os
import atexit

if sys.platform == "win32":
    import win32api
    import win32con
    import shutil
    if not shutil.which("tesseract"):
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            common_paths.append(os.path.join(local_appdata, "Tesseract-OCR", "tesseract.exe"))
        for path in common_paths:
            if os.path.exists(path):
                try:
                    import pytesseract
                    pytesseract.pytesseract.tesseract_cmd = path
                    break
                except Exception:
                    pass

# Global state for pause handling
mouse_hook = None
user_input_detected = False
last_user_activity = time.time()
inactivity_threshold = 5.0  # seconds
is_currently_paused = False
runner_clicking = False
abort_requested = False
cumulative_revenue = 0.0
workflow_variables = {}
_event_counter = 0
_event_counter_lock = threading.Lock()
_context_local = threading.local()
_image_variant_cache: dict[str, list[tuple[str, Any, bool]]] = {}

def cleanup_hook():
    global mouse_hook
    if mouse_hook:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.UnhookWindowsHookEx(mouse_hook)
        except Exception:
            pass
        mouse_hook = None

if sys.platform == "win32":
    atexit.register(cleanup_hook)

def mouse_listener():
    global mouse_hook
    import ctypes
    from ctypes import wintypes
    
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    WH_MOUSE_LL = 14
    
    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_ulonglong)
        ]
        
    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    
    def hook_callback(nCode, wParam, lParam):
        global user_input_detected, last_user_activity, runner_clicking
        if nCode >= 0:
            info = MSLLHOOKSTRUCT.from_address(lParam)
            is_injected = (info.flags & 1) != 0
            if not is_injected:
                last_user_activity = time.time()
                # Ignore synthetic events emitted by the runner itself, but pause on
                # any real user mouse activity: move, wheel, or button interaction.
                if not runner_clicking:
                    user_input_detected = True
        return user32.CallNextHookEx(mouse_hook, nCode, wParam, lParam)
        
    # Maintain reference to prevent garbage collection
    mouse_listener.pointer = HOOKPROC(hook_callback)
    
    mouse_hook = user32.SetWindowsHookExW(
        WH_MOUSE_LL,
        mouse_listener.pointer,
        kernel32.GetModuleHandleW(None),
        0
    )
    
    if not mouse_hook:
        log("Failed to install mouse hook")
        return
        
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

def check_pause_and_wait():
    global user_input_detected, last_user_activity, is_currently_paused
    if sys.platform != "win32":
        return
        
    if user_input_detected or is_currently_paused:
        if not is_currently_paused:
            is_currently_paused = True
            emit_event("runner_paused", reason="user_mouse_activity")
            log("[STATUS] PAUSED")
            log(f"Workflow paused due to user mouse activity. Waiting for {int(inactivity_threshold)}s of inactivity...")
            
        user_input_detected = False
        while True:
            now = time.time()
            time_since_activity = now - last_user_activity
            
            if user_input_detected:
                user_input_detected = False
                last_user_activity = time.time()
                time_since_activity = 0.0
                log("User mouse activity detected again, resetting pause timer...")
                
            if time_since_activity >= inactivity_threshold:
                break
            time.sleep(0.1)
            
        is_currently_paused = False
        emit_event("runner_resumed", reason="mouse_inactive")
        log("[STATUS] RESUMED")
        log(f"No user mouse activity detected for {int(inactivity_threshold)}s. Resuming workflow...")


def wait_with_pause(
    seconds: float,
    *,
    abortable: bool = False,
    label: str | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    global abort_requested
    total = max(0.0, float(seconds))
    remaining = total
    last_progress_marker: float | None = None
    while remaining > 0:
        if abortable and abort_requested:
            log("Wait interrupted by abort request.")
            return
        if stop_event is not None and stop_event.is_set():
            return

        context = current_context()
        if context is not None and total > 0:
            remaining_marker = round(remaining, 1 if total >= 1 else 2)
            if remaining_marker != last_progress_marker:
                emit_event(
                    "task_progress",
                    taskId=context["id"],
                    taskKind=context["kind"],
                    detail=label or f"Waiting {remaining_marker}s",
                    phase="waiting",
                    totalSec=round(total, 2),
                    remainingSec=remaining_marker,
                )
                last_progress_marker = remaining_marker

        check_pause_and_wait()
        chunk = min(0.1, remaining)
        time.sleep(chunk)
        remaining -= chunk


def capture_window_layout() -> list[dict[str, Any]]:
    if sys.platform != "win32":
        return []
        
    import win32gui
    import win32process
    import os
    
    my_pid = os.getpid()
    parent_pid = os.getppid()
    
    layout = []
    
    def enum_cb(hwnd, extra):
        if not win32gui.IsWindowVisible(hwnd):
            return True
            
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
            
        # Filter out system and own process windows
        try:
            _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
            
        if win_pid in (my_pid, parent_pid):
            return True
            
        # Filter out common Windows background windows
        if title in ("Program Manager", "Settings", "Start", "Start menu"):
            return True
            
        # Get position and size
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
            
        w = right - left
        h = bottom - top
        
        # Filter out tiny or empty windows
        if w <= 100 or h <= 100:
            return True
            
        layout.append({
            "title": title,
            "x": left,
            "y": top,
            "width": w,
            "height": h,
            "enabled": True
        })
        return True
        
    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception as e:
        log(f"Error enumerating windows: {e}")
        
    return layout


def restore_window_layout(layout: list[dict[str, Any]]) -> None:
    if sys.platform != "win32" or not layout:
        return
        
    import win32gui
    import win32con
    
    log(f"Restoring layout for {len(layout)} window(s)...")
    
    # Build list of active visible windows
    open_windows = []
    def enum_cb(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                open_windows.append((hwnd, title))
        return True
    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception as e:
        log(f"Error enumerating windows for restore: {e}")
        return
        
    for item in layout:
        if not item.get("enabled", True):
            continue
            
        target_title = item.get("title", "")
        if not target_title:
            continue
            
        # Find matching window by title substring match
        matched_hwnd = None
        for hwnd, title in open_windows:
            if target_title.lower() in title.lower():
                matched_hwnd = hwnd
                break
                
        if matched_hwnd:
            x = int(item["x"])
            y = int(item["y"])
            w = int(item["width"])
            h = int(item["height"])
            log(f"Restoring window '{target_title}' to position ({x}, {y}) size {w}x{h}")
            
            try:
                # Restore window if minimized
                if win32gui.IsIconic(matched_hwnd):
                    # SW_RESTORE = 9
                    win32gui.ShowWindow(matched_hwnd, 9)
                    time.sleep(0.1)
                
                # SWP_NOZORDER = 0x0004, SWP_NOACTIVATE = 0x0010
                win32gui.SetWindowPos(
                    matched_hwnd, 
                    0, 
                    x, y, w, h, 
                    0x0004 | 0x0010
                )
            except Exception as e:
                log(f"Failed to move window '{target_title}': {e}")
        else:
            log(f"Could not find active window matching title '{target_title}' to restore.")


import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def next_event_id(prefix: str) -> str:
    global _event_counter
    with _event_counter_lock:
        _event_counter += 1
        return f"{prefix}-{_event_counter}"


def get_context_stack() -> list[dict[str, Any]]:
    stack = getattr(_context_local, "stack", None)
    if stack is None:
        stack = []
        _context_local.stack = stack
    return stack


def current_context() -> dict[str, Any] | None:
    stack = get_context_stack()
    return stack[-1] if stack else None


def push_context(context: dict[str, Any]) -> None:
    get_context_stack().append(context)


def pop_context(expected_id: str | None = None) -> dict[str, Any] | None:
    stack = get_context_stack()
    if not stack:
        return None
    if expected_id is None or stack[-1].get("id") == expected_id:
        return stack.pop()
    for idx in range(len(stack) - 1, -1, -1):
        if stack[idx].get("id") == expected_id:
            return stack.pop(idx)
    return None


def emit_event(event_type: str, **payload: Any) -> None:
    event_payload = {
        "type": event_type,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "threadId": threading.get_ident(),
        **payload,
    }
    print(f"[EVENT]{json.dumps(event_payload, ensure_ascii=False)}", flush=True)


def summarize_step(step: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "name": step.get("name", ""),
        "type": step.get("type", ""),
    }
    for key in (
        "clickType",
        "image",
        "text",
        "workflowPath",
        "thenWorkflowPath",
        "elseWorkflowPath",
        "intervalId",
        "intervalSec",
        "actionWorkflowPath",
        "stopConditionType",
        "stopImage",
        "stopText",
        "timeoutMs",
        "ms",
        "waitMs",
        "conditionType",
        "command",
        "key",
        "amount",
        "variableName",
        "operator",
        "value",
    ):
        if key in step and step.get(key) not in (None, ""):
            summary[key] = step.get(key)
    return summary


def build_context(kind: str, title: str, **payload: Any) -> dict[str, Any]:
    context = {
        "id": payload.pop("id", next_event_id(kind)),
        "kind": kind,
        "title": title,
        "parentId": payload.pop("parentId", current_context().get("id") if current_context() else None),
        **payload,
    }
    return context


_actual_scale = None

def get_actual_scale() -> float:
    global _actual_scale
    if _actual_scale is not None:
        return _actual_scale
    if sys.platform != "win32":
        _actual_scale = 1.0
        return _actual_scale
    try:
        import pyautogui
        from PIL import ImageGrab
        logical_w, _ = pyautogui.size()
        # Grab primary screen only to calculate standard scale factor
        full_img = ImageGrab.grab(all_screens=False)
        captured_w, _ = full_img.size
        _actual_scale = captured_w / logical_w
        log(f"Dynamic DPI scaling calculated: {captured_w} (Pillow) / {logical_w} (PyAutoGUI) = {_actual_scale}")
        return _actual_scale
    except Exception as err:
        log(f"Error calculating dynamic DPI scale: {err}")
        return 1.0


def take_screenshot(region=None) -> Any:
    from PIL import ImageGrab
    if region and isinstance(region, (list, tuple)) and len(region) >= 4:
        try:
            x, y, w, h = float(region[0]), float(region[1]), float(region[2]), float(region[3])
            if w <= 0 or h <= 0:
                log(f"Warning: Invalid region size ({w}x{h}). Falling back to full screen grab.")
                return ImageGrab.grab(all_screens=True)
            
            # Since the process is not DPI-aware, GDI / ImageGrab.grab expects LOGICAL coordinates
            scale = get_actual_scale()
            logical_region = (
                int(x / scale),
                int(y / scale),
                int((x + w) / scale),
                int((y + h) / scale),
            )
            try:
                return ImageGrab.grab(bbox=logical_region, all_screens=True)
            except Exception as err:
                log(f"ImageGrab.grab with bbox {logical_region} failed: {err}. Falling back to virtual screen grab and crop.")
                full_img = ImageGrab.grab(all_screens=True)
                if sys.platform == "win32":
                    try:
                        import ctypes
                        user32 = ctypes.windll.user32
                        min_x = user32.GetSystemMetrics(76) # SM_XVIRTUALSCREEN (logical)
                        min_y = user32.GetSystemMetrics(77) # SM_YVIRTUALSCREEN (logical)
                    except Exception:
                        min_x = 0
                        min_y = 0
                else:
                    min_x = 0
                    min_y = 0
                
                # Convert logical min_x, min_y back to physical coordinates
                physical_min_x = int(min_x * scale)
                physical_min_y = int(min_y * scale)
                
                adjusted_region = (
                    int(x - physical_min_x),
                    int(y - physical_min_y),
                    int(x + w - physical_min_x),
                    int(y + h - physical_min_y),
                )
                return full_img.crop(adjusted_region)
        except Exception as e:
            log(f"Error parsing region coordinates {region}: {e}. Grabbing all screens.")
            return ImageGrab.grab(all_screens=True)
    return ImageGrab.grab(all_screens=True)


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
    screenshot = take_screenshot(region)
    try:
        screenshot.save("debug_ocr_region.png")
        log("Saved OCR region screenshot to debug_ocr_region.png")
    except Exception as e:
        log(f"Failed to save debug OCR screenshot: {e}")

    variants = prepare_ocr_variants(screenshot, threshold)
    extracted_results: list[str] = []
    for idx, variant in enumerate(variants):
        text = pytesseract.image_to_string(variant, lang=lang, config=tesseract_config).strip()
        log(f"OCR Variant {idx} saw: '{text}'")
        extracted_results.append(text)

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


def _decode_data_url_image(image: str) -> bytes:
    _, _, encoded = image.partition("base64,")
    if not encoded:
        raise ValueError("Invalid data URL image payload.")
    return base64.b64decode(encoded)


def load_image_variants(image: str) -> list[tuple[str, Any, bool]]:
    cached = _image_variant_cache.get(image)
    if cached is not None:
        return cached

    from PIL import Image, ImageOps

    if image.startswith("data:"):
        base_img = Image.open(io.BytesIO(_decode_data_url_image(image)))
    else:
        base_img = Image.open(image)

    base_rgba = base_img.convert("RGBA")
    white_background = Image.new("RGBA", base_rgba.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_background, base_rgba).convert("RGB")
    grayscale = ImageOps.grayscale(composited)

    variants: list[tuple[str, Any, bool]] = [
        ("rgb", composited, False),
        ("grayscale", grayscale, True),
    ]
    _image_variant_cache[image] = variants
    return variants


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
        from PIL import ImageOps

        screenshot = take_screenshot(region)
        screenshot_variants = [
            ("rgb", screenshot, False),
            ("grayscale", ImageOps.grayscale(screenshot), True),
        ]
        template_variants = load_image_variants(image)
        confidence_levels = [float(confidence)]
        fallback_confidence = round(max(0.6, float(confidence) - 0.05), 2)
        if fallback_confidence < confidence:
            confidence_levels.append(fallback_confidence)

        for confidence_level in confidence_levels:
            for template_name, template_variant, template_grayscale in template_variants:
                for screenshot_name, screenshot_variant, screenshot_grayscale in screenshot_variants:
                    grayscale = template_grayscale or screenshot_grayscale
                    match = pyautogui.locate(
                        template_variant,
                        screenshot_variant,
                        confidence=confidence_level,
                        grayscale=grayscale,
                    )

                    if match:
                        if (
                            confidence_level != confidence
                            or template_name != "rgb"
                            or screenshot_name != "rgb"
                        ):
                            log(
                                "Image locate fallback matched "
                                f"templateVariant={template_name} screenshotVariant={screenshot_name} "
                                f"confidence={confidence_level}"
                            )

                        if region:
                            try:
                                from pyautogui import Box
                            except ImportError:
                                from collections import namedtuple
                                Box = namedtuple('Box', 'left top width height')

                            left = match[0] + int(region[0])
                            top = match[1] + int(region[1])
                            return Box(left, top, match[2], match[3]), None

                        return match, None

        return None, None
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
    global runner_clicking
    runner_clicking = True
    try:
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
    finally:
        time.sleep(0.05)
        runner_clicking = False


def perform_double_click(
    pyautogui: Any,
    x: Any,
    y: Any,
    interval: float = 0.15,
    button: str = "left",
) -> tuple[int, int, str]:
    global runner_clicking
    runner_clicking = True
    try:
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
    finally:
        time.sleep(0.05)
        runner_clicking = False


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
        try:
            img.save("debug_ocr_region.png")
            log("Saved OCR region screenshot to debug_ocr_region.png")
        except Exception as e:
            log(f"Failed to save debug OCR screenshot: {e}")

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
        wait_with_pause(delay_before, abortable=True)

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
                check_pause_and_wait()
                match, locate_error = safe_locate_on_screen(pyautogui, image, confidence=confidence, region=region)
                if locate_error:
                    last_locate_error = locate_error
                if match:
                    center_point = pyautogui.center(match)
                    scale = get_actual_scale()
                    click_x = center_point.x / scale
                    click_y = center_point.y / scale
                    
                    highlight_coordinate(int(click_x), int(click_y))
                    
                    mouse_before = get_mouse_position(pyautogui)
                    frontmost_before = get_frontmost_app_name()
                    log(
                        f"Found image match={match} center=({int(click_x)}, {int(click_y)}) "
                        f"mouseBefore={mouse_before} frontmostBefore={frontmost_before}"
                    )
                    screen_x, screen_y, backend = perform_click(pyautogui, click_x, click_y)
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
                check_pause_and_wait()
                with gui_lock:
                    screenshot = take_screenshot(region)
                
                match_box = locate_text_in_image(screenshot, text_val)
                if match_box:
                    left, top, width, height = match_box
                    
                    offset_x = region[0] if region else 0
                    offset_y = region[1] if region else 0
                    
                    center_x_phys = offset_x + left + width / 2
                    center_y_phys = offset_y + top + height / 2
                    
                    scale = get_actual_scale()
                    center_x = int(center_x_phys / scale)
                    center_y = int(center_y_phys / scale)
                    
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
        click_mode = step.get("clickMode", "single")
        points = step.get("points", [])
        if click_mode == "random" and points:
            index_var_name = step.get("indexVariable", "").strip()
            selected_point = None
            if index_var_name:
                var_val = workflow_variables.get(index_var_name)
                if var_val is not None:
                    try:
                        idx = int(float(var_val))
                        if 0 <= idx < len(points):
                            selected_point = points[idx]
                            log(f"Selected point at index {idx} ({selected_point.get('x')}, {selected_point.get('y')}) using variable '{index_var_name}' from {len(points)} points.")
                        else:
                            log(f"Index {idx} from variable '{index_var_name}' is out of range [0, {len(points)-1}]. Selecting random point.")
                    except (ValueError, TypeError) as e:
                        log(f"Warning: Index variable '{index_var_name}' value '{var_val}' is not a valid number. Selecting random point. Error: {e}")
                else:
                    log(f"Variable '{index_var_name}' is not defined. Selecting random point.")
            
            if selected_point is None:
                import random
                selected_point = random.choice(points)
                log(f"Random click mode enabled. Selected point ({selected_point.get('x')}, {selected_point.get('y')}) from {len(points)} points.")
            
            x_phys = selected_point.get("x")
            y_phys = selected_point.get("y")
        else:
            x_phys = step.get("x")
            y_phys = step.get("y")

        if x_phys is None or y_phys is None:
            raise ValueError("Coordinates x and y are required for click by coordinate.")
        scale = get_actual_scale()
        x = x_phys / scale
        y = y_phys / scale
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
        wait_with_pause(delay_after, abortable=True)


def step_double_click(step: dict[str, Any], dry_run: bool) -> None:
    delay_before = float(step.get("delayBeforeSec", 0))
    if delay_before > 0:
        log(f"Waiting {delay_before}s before double click...")
        wait_with_pause(delay_before, abortable=True)

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
                check_pause_and_wait()
                match, locate_error = safe_locate_on_screen(pyautogui, image, confidence=confidence, region=region)
                if locate_error:
                    last_locate_error = locate_error
                if match:
                    center_point = pyautogui.center(match)
                    scale = get_actual_scale()
                    click_x = center_point.x / scale
                    click_y = center_point.y / scale
                    
                    highlight_coordinate(int(click_x), int(click_y))
                    
                    mouse_before = get_mouse_position(pyautogui)
                    frontmost_before = get_frontmost_app_name()
                    log(
                        f"Found image match={match} center=({int(click_x)}, {int(click_y)}) "
                        f"mouseBefore={mouse_before} frontmostBefore={frontmost_before}"
                    )
                    screen_x, screen_y, backend = perform_double_click(pyautogui, click_x, click_y, interval=interval)
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
                check_pause_and_wait()
                with gui_lock:
                    screenshot = take_screenshot(region)
                
                match_box = locate_text_in_image(screenshot, text_val)
                if match_box:
                    left, top, width, height = match_box
                    
                    offset_x = region[0] if region else 0
                    offset_y = region[1] if region else 0
                    
                    center_x_phys = offset_x + left + width / 2
                    center_y_phys = offset_y + top + height / 2
                    
                    scale = get_actual_scale()
                    center_x = int(center_x_phys / scale)
                    center_y = int(center_y_phys / scale)
                    
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
        click_mode = step.get("clickMode", "single")
        points = step.get("points", [])
        if click_mode == "random" and points:
            index_var_name = step.get("indexVariable", "").strip()
            selected_point = None
            if index_var_name:
                var_val = workflow_variables.get(index_var_name)
                if var_val is not None:
                    try:
                        idx = int(float(var_val))
                        if 0 <= idx < len(points):
                            selected_point = points[idx]
                            log(f"Selected point at index {idx} ({selected_point.get('x')}, {selected_point.get('y')}) using variable '{index_var_name}' from {len(points)} points.")
                        else:
                            log(f"Index {idx} from variable '{index_var_name}' is out of range [0, {len(points)-1}]. Selecting random point.")
                    except (ValueError, TypeError) as e:
                        log(f"Warning: Index variable '{index_var_name}' value '{var_val}' is not a valid number. Selecting random point. Error: {e}")
                else:
                    log(f"Variable '{index_var_name}' is not defined. Selecting random point.")
            
            if selected_point is None:
                import random
                selected_point = random.choice(points)
                log(f"Random double click mode enabled. Selected point ({selected_point.get('x')}, {selected_point.get('y')}) from {len(points)} points.")
            
            x_phys = selected_point.get("x")
            y_phys = selected_point.get("y")
        else:
            x_phys = step.get("x")
            y_phys = step.get("y")

        if x_phys is None or y_phys is None:
            raise ValueError("Coordinates x and y are required for double click by coordinate.")
        scale = get_actual_scale()
        x = x_phys / scale
        y = y_phys / scale
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
        wait_with_pause(delay_after, abortable=True)


def step_drag(step: dict[str, Any], dry_run: bool) -> None:
    delay_before = float(step.get("delayBeforeSec", 0))
    if delay_before > 0:
        log(f"Waiting {delay_before}s before drag...")
        wait_with_pause(delay_before, abortable=True)

    start_x_phys = step.get("startX")
    start_y_phys = step.get("startY")
    end_x_phys = step.get("endX")
    end_y_phys = step.get("endY")
    duration = float(step.get("durationSec", 0.5))
    button = step.get("button", "left").lower()

    if start_x_phys is None or start_y_phys is None or end_x_phys is None or end_y_phys is None:
        raise ValueError("startX, startY, endX, and endY are required for drag step.")

    scale = get_actual_scale()
    start_x = start_x_phys / scale
    start_y = start_y_phys / scale
    end_x = end_x_phys / scale
    end_y = end_y_phys / scale

    if dry_run:
        log(f"DRY RUN drag from ({start_x}, {start_y}) to ({end_x}, {end_y}) over {duration}s button={button}")
    else:
        try:
            import pyautogui  # type: ignore
        except ImportError as error:
            raise RuntimeError("pyautogui is required for drag action.") from error

        log(f"Dragging from ({start_x}, {start_y}) to ({end_x}, {end_y}) over {duration}s button={button}")
        pyautogui.moveTo(start_x, start_y)
        pyautogui.dragTo(end_x, end_y, duration=duration, button=button)

    delay_after = float(step.get("delayAfterSec", 0))
    if delay_after > 0:
        log(f"Waiting {delay_after}s after drag...")
        wait_with_pause(delay_after, abortable=True)


def step_scroll(step: dict[str, Any], dry_run: bool) -> None:
    delay_before = float(step.get("delayBeforeSec", 0))
    if delay_before > 0:
        log(f"Waiting {delay_before}s before scroll...")
        wait_with_pause(delay_before, abortable=True)

    amount = int(step.get("amount", 0))
    x_phys = step.get("x")
    y_phys = step.get("y")

    scale = get_actual_scale()
    x = x_phys / scale if x_phys is not None else None
    y = y_phys / scale if y_phys is not None else None

    if dry_run:
        log(f"DRY RUN scroll amount={amount} at x={x}, y={y}")
    else:
        try:
            import pyautogui  # type: ignore
        except ImportError as error:
            raise RuntimeError("pyautogui is required for scroll action.") from error

        log(f"Scrolling amount={amount} at x={x}, y={y}")
        if x is not None and y is not None:
            pyautogui.scroll(amount, x=int(x), y=int(y))
        else:
            pyautogui.scroll(amount)

    delay_after = float(step.get("delayAfterSec", 0))
    if delay_after > 0:
        log(f"Waiting {delay_after}s after scroll...")
        wait_with_pause(delay_after, abortable=True)


def step_wait(step: dict[str, Any]) -> None:
    ms = step["ms"]
    log(f"Waiting {ms} ms")
    wait_with_pause(ms / 1000.0, abortable=True, label=f"Chờ {round(ms / 1000.0, 2)}s")


def step_wait_for_image(step: dict[str, Any], dry_run: bool) -> None:
    global abort_requested
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
    last_reported_second: int | None = None
    while time.time() - start < timeout / 1000:
        if abort_requested:
            log("Wait for image interrupted by abort request.")
            return
        check_pause_and_wait()
        elapsed = time.time() - start
        elapsed_second = int(elapsed)
        if elapsed_second != last_reported_second:
            context = current_context()
            if context is not None:
                emit_event(
                    "task_progress",
                    taskId=context["id"],
                    taskKind=context["kind"],
                    detail=f"Tìm hình ảnh {os.path.basename(image) or image}",
                    phase="searching_image",
                    elapsedSec=round(elapsed, 1),
                    timeoutSec=round(timeout / 1000.0, 1),
                )
            last_reported_second = elapsed_second
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
    global abort_requested
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
    last_reported_second: int | None = None
    while time.time() - start < timeout / 1000:
        if abort_requested:
            log("Check text interrupted by abort request.")
            return
        check_pause_and_wait()
        elapsed = time.time() - start
        elapsed_second = int(elapsed)
        if elapsed_second != last_reported_second:
            context = current_context()
            if context is not None:
                emit_event(
                    "task_progress",
                    taskId=context["id"],
                    taskKind=context["kind"],
                    detail=f"Kiểm tra chữ '{text}'",
                    phase="checking_text",
                    elapsedSec=round(elapsed, 1),
                    timeoutSec=round(timeout / 1000.0, 1),
                )
            last_reported_second = elapsed_second
        log(f"Region: {region}")
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
    check_pause_and_wait()
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
                screenshot = take_screenshot(region)
                try:
                    screenshot.save("debug_ocr_region.png")
                    log("Saved OCR region screenshot to debug_ocr_region.png")
                except Exception as e:
                    log(f"Failed to save debug OCR screenshot: {e}")
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
            wait_with_pause(wait_ms / 1000.0, abortable=True)
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
    check_pause_and_wait()
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
                    screenshot = take_screenshot(region)
                try:
                    screenshot.save("debug_ocr_region.png")
                    log("Saved OCR region screenshot to debug_ocr_region.png")
                except Exception as e:
                    log(f"Failed to save debug OCR screenshot: {e}")
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

    parent_context = current_context()
    interval_context = build_context(
        "interval",
        f"Interval {interval_id}",
        parentId=parent_context["id"] if parent_context else None,
        intervalId=interval_id,
        intervalSec=float(step.get("intervalSec", 5)),
        actionWorkflowPath=step.get("actionWorkflowPath"),
        stopConditionType=step.get("stopConditionType"),
    )

    with intervals_lock:
        if interval_id in active_intervals:
            log(f"Interval {interval_id} is already running. Stopping it first.")
            active_intervals[interval_id]["stop_event"].set()
            time.sleep(0.5)

        stop_event = threading.Event()
        t = threading.Thread(
            target=interval_worker,
            args=(interval_id, step, dry_run, stop_event, interval_context),
            daemon=True
        )
        active_intervals[interval_id] = {
            "thread": t,
            "stop_event": stop_event,
            "event_id": interval_context["id"],
        }
        t.start()

def interval_worker(
    interval_id: str,
    step: dict[str, Any],
    dry_run: bool,
    stop_event: threading.Event,
    interval_context: dict[str, Any],
) -> None:
    interval_sec = float(step.get("intervalSec", 5))
    action_workflow_path = resolve_workflow_path(step.get("actionWorkflowPath", "")) if step.get("actionWorkflowPath") else None
    
    stop_cond_type = step.get("stopConditionType")
    stop_image = step.get("stopImage")
    stop_confidence = float(step.get("stopConfidence", 0.8))
    stop_text = step.get("stopText")
    stop_region = step.get("stopRegion")

    push_context(interval_context)
    emit_event("interval_started", **interval_context)
    log(f"[Interval {interval_id}] Worker thread started. Interval: {interval_sec}s")

    try:
        iteration = 0
        while not stop_event.is_set():
            iteration += 1
            emit_event(
                "task_progress",
                taskId=interval_context["id"],
                taskKind="interval",
                detail=f"Kiểm tra chu kỳ lần {iteration}",
                phase="checking_interval",
                iteration=iteration,
                intervalId=interval_id,
            )

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
                            screenshot = take_screenshot(stop_region)
                        try:
                            screenshot.save("debug_ocr_region.png")
                            log("Saved OCR region screenshot to debug_ocr_region.png")
                        except Exception as e:
                            log(f"Failed to save debug OCR screenshot: {e}")
                        extracted = pytesseract.image_to_string(screenshot)
                        condition_met = stop_text.lower() in extracted.lower()
                    except Exception as err:
                        log(f"[Interval {interval_id}] Error checking stop text: {err}")

            if condition_met:
                emit_event(
                    "interval_stopped",
                    id=interval_context["id"],
                    detail=f"Dừng vì thỏa điều kiện {stop_cond_type or 'stop'}",
                    reason="condition_met",
                )
                log(f"[Interval {interval_id}] Stop condition met ({stop_cond_type}). Clearing interval.")
                break

            if action_workflow_path:
                emit_event(
                    "task_progress",
                    taskId=interval_context["id"],
                    taskKind="interval",
                    detail=f"Chạy workflow con {os.path.basename(action_workflow_path)}",
                    phase="running_sub_workflow",
                    intervalId=interval_id,
                )
                log(f"[Interval {interval_id}] Triggering sub-workflow: {action_workflow_path}")
                try:
                    if os.path.exists(action_workflow_path):
                        step_run_workflow({"workflowPath": action_workflow_path}, dry_run, depth=0)
                    else:
                        log(f"[Interval {interval_id}] Action workflow path does not exist: {action_workflow_path}")
                except Exception as err:
                    log(f"[Interval {interval_id}] Error executing action workflow: {err}")

            wait_with_pause(
                interval_sec,
                label=f"Chờ {round(interval_sec, 2)}s trước lần kiểm tra tiếp theo",
                stop_event=stop_event,
            )

        if stop_event.is_set():
            emit_event(
                "interval_stopped",
                id=interval_context["id"],
                detail="Đã dừng theo yêu cầu",
                reason="stop_requested",
            )
    finally:
        with intervals_lock:
            if interval_id in active_intervals:
                del active_intervals[interval_id]
        pop_context(interval_context["id"])
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

def step_set_variable(step: dict[str, Any], dry_run: bool) -> None:
    global workflow_variables
    var_name = step.get("variableName", "").strip()
    if not var_name:
        log("Error: variableName is empty in set_variable step")
        return
    operator = step.get("operator", "set")
    raw_val = step.get("value", "0")
    
    # Try to parse numeric value
    try:
        val = float(raw_val)
        if val.is_integer():
            val = int(val)
    except ValueError:
        val = raw_val
        
    if dry_run:
        log(f"DRY RUN set_variable '{var_name}' {operator} '{val}'")
        return
        
    current = workflow_variables.get(var_name, 0)
    
    def to_numeric(v):
        try:
            num = float(v)
            if num.is_integer():
                return int(num)
            return num
        except (ValueError, TypeError):
            return None

    current_num = to_numeric(current)
    val_num = to_numeric(val)

    if operator == "add":
        if current_num is not None and val_num is not None:
            new_val = current_num + val_num
        else:
            new_val = str(current) + str(val)
    elif operator == "subtract":
        if current_num is not None and val_num is not None:
            new_val = current_num - val_num
        else:
            log(f"Warning: Cannot subtract non-numeric values: {current} and {val}")
            new_val = current
    elif operator == "multiply":
        if current_num is not None and val_num is not None:
            new_val = current_num * val_num
        else:
            log(f"Warning: Cannot multiply non-numeric values: {current} and {val}")
            new_val = current
    elif operator == "divide":
        if current_num is not None and val_num is not None:
            if val_num == 0:
                log("Warning: Division by zero")
                new_val = current
            else:
                new_val = current_num / val_num
                if isinstance(new_val, float) and new_val.is_integer():
                    new_val = int(new_val)
        else:
            log(f"Warning: Cannot divide non-numeric values: {current} and {val}")
            new_val = current
    else: # set
        new_val = val
        
    workflow_variables[var_name] = new_val
    log(f"Variable '{var_name}' updated: {current} -> {new_val}")

def step_conditional_variable(step: dict[str, Any], dry_run: bool, depth: int) -> None:
    global workflow_variables
    var_name = step.get("variableName", "").strip()
    if not var_name:
        log("Error: variableName is empty in conditional_variable step")
        return
        
    operator = step.get("operator", "==")
    raw_val = step.get("value", "0")
    
    current = workflow_variables.get(var_name, 0)
    
    # Try to parse both current and compared value as float/int for numeric comparison
    val_to_compare = raw_val
    try:
        parsed_compare = float(raw_val)
        parsed_current = float(current)
        # Both parsed successfully, compare as numbers
        val_to_compare = parsed_compare
        current_val = parsed_current
    except (ValueError, TypeError):
        # Otherwise compare as strings
        val_to_compare = str(raw_val)
        current_val = str(current)
        
    condition_met = False
    if operator == "==":
        condition_met = current_val == val_to_compare
    elif operator == "!=":
        condition_met = current_val != val_to_compare
    elif operator == ">":
        condition_met = current_val > val_to_compare
    elif operator == "<":
        condition_met = current_val < val_to_compare
    elif operator == ">=":
        condition_met = current_val >= val_to_compare
    elif operator == "<=":
        condition_met = current_val <= val_to_compare
    else:
        log(f"Warning: Unsupported operator '{operator}' in conditional_variable step")
        
    if dry_run:
        log(f"DRY RUN conditional_variable: is '{var_name}'({current}) {operator} '{raw_val}'? -> {condition_met}")
        # In dry run, assume condition is met for testing paths if provided
        condition_met = True
        
    if condition_met:
        then_path = step.get("thenWorkflowPath")
        if then_path:
            then_resolved = resolve_workflow_path(then_path)
            log(f"Variable condition MET. Running THEN workflow: {then_resolved}")
            step_run_workflow({"workflowPath": then_resolved}, dry_run, depth)
        else:
            log("Variable condition MET, but no thenWorkflowPath specified.")
    else:
        else_path = step.get("elseWorkflowPath")
        if else_path:
            else_resolved = resolve_workflow_path(else_path)
            log(f"Variable condition NOT met. Running ELSE workflow: {else_resolved}")
            step_run_workflow({"workflowPath": else_resolved}, dry_run, depth)
        else:
            log("Variable condition NOT met, and no elseWorkflowPath specified. Skipping.")

def execute_step_list(steps: list[dict[str, Any]], dry_run: bool, label: str, step_delay: float = 0.0, depth: int = 0) -> None:
    global abort_requested
    sequence_context = build_context(
        "sequence",
        f"Sequence: {label}",
        label=label,
        depth=depth,
        totalSteps=len(steps),
    )
    push_context(sequence_context)
    emit_event("sequence_started", **sequence_context)
    log(f"Running {label} sequence with {len(steps)} step(s)")
    try:
        for index, step in enumerate(steps, start=1):
            if abort_requested:
                log("Execution aborted due to background signal.")
                break
            check_pause_and_wait()
            step_type = step["type"]
            step_context = build_context(
                "step",
                step.get("name", step_type),
                label=label,
                depth=depth,
                stepIndex=index,
                totalSteps=len(steps),
                stepType=step_type,
                step=summarize_step(step),
                sequenceId=sequence_context["id"],
            )
            push_context(step_context)
            emit_event("step_started", **step_context)
            log(f"Step {index}/{len(steps)}: {step.get('name', step_type)} [{step_type}]")

            try:
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
                elif step_type == "abort_iteration":
                    abort_requested = True
                    log("Abort iteration request set.")
                elif step_type == "send_telegram":
                    with gui_lock:
                        step_send_telegram(step, dry_run)
                elif step_type == "drag":
                    with gui_lock:
                        step_drag(step, dry_run)
                elif step_type == "scroll":
                    with gui_lock:
                        step_scroll(step, dry_run)
                elif step_type == "set_variable":
                    step_set_variable(step, dry_run)
                elif step_type == "conditional_variable":
                    step_conditional_variable(step, dry_run, depth)
                else:
                    raise ValueError(f"Unsupported step type: {step_type}")
                emit_event(
                    "step_completed",
                    id=step_context["id"],
                    detail="Hoàn thành",
                    stepIndex=step_context["stepIndex"],
                    totalSteps=step_context["totalSteps"],
                    depth=step_context["depth"],
                    label=step_context["label"],
                )
            except Exception as error:
                emit_event(
                    "step_failed",
                    id=step_context["id"],
                    detail=str(error),
                    errorType=type(error).__name__,
                    stepIndex=step_context["stepIndex"],
                    totalSteps=step_context["totalSteps"],
                    depth=step_context["depth"],
                    label=step_context["label"],
                )
                raise
            finally:
                pop_context(step_context["id"])

            if step_delay > 0 and index < len(steps):
                log(f"Waiting {step_delay}s between steps...")
                wait_with_pause(
                    step_delay,
                    abortable=True,
                    label=f"Nghỉ {round(step_delay, 2)}s trước bước tiếp theo",
                )
    finally:
        emit_event("sequence_finished", id=sequence_context["id"], detail="Sequence finished")
        pop_context(sequence_context["id"])

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

def send_telegram_message(bot_token: str, chat_id: str, message: str, photo_bytes: bytes = None) -> None:
    import urllib.request
    import urllib.error
    import urllib.parse
    
    # Percent-encode bot_token to prevent UnicodeEncodeError in case it contains non-ASCII characters
    safe_token = urllib.parse.quote(bot_token)
    
    if photo_bytes:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        parts = []
        
        parts.append(f"--{boundary}".encode('utf-8'))
        parts.append(b'Content-Disposition: form-data; name="chat_id"')
        parts.append(b'')
        parts.append(str(chat_id).encode('utf-8'))
        
        if message:
            parts.append(f"--{boundary}".encode('utf-8'))
            parts.append(b'Content-Disposition: form-data; name="caption"')
            parts.append(b'')
            parts.append(message.encode('utf-8'))
            
        parts.append(f"--{boundary}".encode('utf-8'))
        parts.append(b'Content-Disposition: form-data; name="photo"; filename="screenshot.png"')
        parts.append(b'Content-Type: image/png')
        parts.append(b'')
        parts.append(photo_bytes)
        
        parts.append(f"--{boundary}--".encode('utf-8'))
        parts.append(b'')
        
        body = b'\r\n'.join(parts)
        url = f"https://api.telegram.org/bot{safe_token}/sendPhoto"
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body))
        }
    else:
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message
        }).encode('utf-8')
        url = f"https://api.telegram.org/bot{safe_token}/sendMessage"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        body = data
        
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = response.read().decode('utf-8')
            log(f"Telegram notification sent: {res_data}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        raise RuntimeError(f"Telegram API failed ({e.code}): {err_body}")
    except Exception as e:
        raise RuntimeError(f"Failed to send Telegram notification: {e}")

def parse_revenue_from_text(text: str) -> float:
    import re
    text_upper = text.upper().strip()
    log(f"Original OCR text for parsing: '{text_upper}'")
    
    # Remove spaces between digits, e.g. "150 000" -> "150000"
    text_clean = re.sub(r'(?<=\d)\s+(?=\d)', '', text_upper)
    # Remove spaces around dots or commas between digits, e.g. "150 . 000" -> "150.000"
    text_clean = re.sub(r'(?<=\d)\s*([.,])\s*(?=\d)', r'\1', text_clean)
    log(f"Cleaned OCR text: '{text_clean}'")
    
    matches = re.findall(r'[\d.,]+', text_clean)
    if not matches:
        return 0.0
        
    parsed_values = []
    for num_str in matches:
        if num_str in ('.', ','):
            continue
            
        temp_str = num_str
        if temp_str.count('.') > 1:
            temp_str = temp_str.replace('.', '')
        if temp_str.count(',') > 1:
            temp_str = temp_str.replace(',', '')
            
        if ',' in temp_str and '.' in temp_str:
            comma_idx = temp_str.index(',')
            dot_idx = temp_str.index('.')
            if comma_idx < dot_idx:
                temp_str = temp_str.replace(',', '')
            else:
                temp_str = temp_str.replace('.', '').replace(',', '.')
        elif ',' in temp_str:
            parts = temp_str.split(',')
            if len(parts) == 2 and len(parts[1]) in (1, 2):
                temp_str = temp_str.replace(',', '.')
            else:
                temp_str = temp_str.replace(',', '')
        elif '.' in temp_str:
            parts = temp_str.split('.')
            if len(parts) == 2 and len(parts[1]) == 3:
                temp_str = temp_str.replace('.', '')
                
        try:
            val = float(temp_str)
            idx = text_clean.find(num_str)
            if idx != -1:
                after_str = text_clean[idx + len(num_str):].strip()
                if after_str.startswith('K'):
                    val *= 1000
                elif after_str.startswith('M'):
                    val *= 1000000
            parsed_values.append(val)
        except ValueError:
            pass
            
    if not parsed_values:
        return 0.0
        
    val = max(parsed_values)
    return val

def format_vietnamese_money(value: float) -> str:
    return f"{int(value):,}".replace(",", ".")


def normalize_optional_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def mask_secret(value: str, *, keep_start: int = 6, keep_end: int = 4) -> str:
    if not value:
        return "(empty)"
    if len(value) <= keep_start + keep_end:
        return "*" * len(value)
    return f"{value[:keep_start]}...{value[-keep_end:]}"

def step_send_telegram(step: dict[str, Any], dry_run: bool) -> None:
    global cumulative_revenue
    bot_token = normalize_optional_string(step.get("botToken"))
    chat_id = normalize_optional_string(step.get("chatId"))
    message = step.get("message", "")
    ocr_revenue = step.get("ocrRevenue", False)
    ocr_text = step.get("ocrText", False)
    region = step.get("region")
    
    if not bot_token or not chat_id:
        raise ValueError("botToken and chatId are required for send_telegram step.")
        
    if dry_run:
        if ocr_revenue:
            log(f"DRY RUN send_telegram OCR revenue to chatId={chat_id} message='{message}' region={region}")
        elif ocr_text:
            log(f"DRY RUN send_telegram OCR text to chatId={chat_id} message='{message}' region={region}")
        else:
            log(f"DRY RUN send_telegram to chatId={chat_id} message='{message}' region={region}")
        return
        
    # Always capture the screenshot of the region to send
    photo_bytes = None
    screenshot = None
    try:
        if region:
            log(f"Capturing region screenshot: {region}")
            screenshot = take_screenshot(region)
        else:
            log("Warning: No region specified for send_telegram step. Capturing all screens.")
            screenshot = take_screenshot(None)
            
        import io
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        photo_bytes = img_byte_arr.read()
        log("Captured screenshot of region for Telegram notification.")
    except Exception as e:
        log(f"Failed to capture region screenshot: {e}.")

    if ocr_revenue:
        try:
            extracted_text = ""
            if screenshot:
                log("Performing OCR on the captured screenshot to detect revenue...")
                try:
                    import pytesseract
                    variants = prepare_ocr_variants(screenshot, threshold=None)
                    extracted_results: list[str] = []
                    for idx, variant in enumerate(variants):
                        text = pytesseract.image_to_string(variant, lang="eng", config="--psm 6").strip()
                        log(f"OCR Variant {idx} saw: '{text}'")
                        extracted_results.append(text)
                    
                    extracted_results.sort(key=len, reverse=True)
                    extracted_text = extracted_results[0] if extracted_results else ""
                except Exception as ocr_err:
                    log(f"OCR execution failed: {ocr_err}")
            else:
                log("No screenshot available to perform OCR.")
                
            log(f"OCR extracted text: '{extracted_text}'")
            current_val = parse_revenue_from_text(extracted_text)
            cumulative_revenue += current_val
            log(f"Parsed current revenue: {current_val} (formatted: {format_vietnamese_money(current_val)})")
            log(f"Cumulative total revenue: {cumulative_revenue} (formatted: {format_vietnamese_money(cumulative_revenue)})")
            
            current_str = format_vietnamese_money(current_val)
            total_str = format_vietnamese_money(cumulative_revenue)
            formatted_message = message.replace("{current}", current_str).replace("{total}", total_str)
            
            send_telegram_message(bot_token, chat_id, formatted_message, photo_bytes)
        except Exception as e:
            log(f"Failed to perform OCR revenue or send message: {e}")
            raise
    elif ocr_text:
        try:
            extracted_text = ""
            if screenshot:
                log("Performing OCR on the captured screenshot to extract text...")
                try:
                    import pytesseract
                    variants = prepare_ocr_variants(screenshot, threshold=None)
                    extracted_results: list[str] = []
                    for idx, variant in enumerate(variants):
                        text = pytesseract.image_to_string(variant, lang="eng", config="--psm 6").strip()
                        log(f"OCR Variant {idx} saw: '{text}'")
                        extracted_results.append(text)
                    
                    extracted_results.sort(key=len, reverse=True)
                    extracted_text = extracted_results[0] if extracted_results else ""
                except Exception as ocr_err:
                    log(f"OCR execution failed: {ocr_err}")
            else:
                log("No screenshot available to perform OCR.")
                
            log(f"OCR extracted text: '{extracted_text}'")
            if "{text}" in message:
                formatted_message = message.replace("{text}", extracted_text)
            else:
                if message:
                    formatted_message = f"{message}\n{extracted_text}"
                else:
                    formatted_message = extracted_text
            
            send_telegram_message(bot_token, chat_id, formatted_message, photo_bytes)
        except Exception as e:
            log(f"Failed to perform OCR text or send message: {e}")
            raise
    else:
        send_telegram_message(bot_token, chat_id, message, photo_bytes)



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
    wait_with_pause(seconds)


def execute_workflow(workflow: dict[str, Any]) -> None:
    global abort_requested, cumulative_revenue, workflow_variables
    abort_requested = False
    cumulative_revenue = 0.0
    workflow_variables = {}
    root_context = build_context(
        "workflow",
        workflow.get("name", "untitled"),
        workflowName=workflow.get("name", "untitled"),
    )
    push_context(root_context)
    emit_event("workflow_started", **root_context)
    
    if sys.platform == "win32":
        t = threading.Thread(target=mouse_listener, daemon=True)
        t.start()
        log("Started background mouse listener thread.")

    settings = workflow.get("settings", {})
    deviceName = settings.get("deviceName", "Thiết bị")
    bot_token = normalize_optional_string(settings.get("telegramBotToken"))
    chat_id = normalize_optional_string(settings.get("telegramChatId"))
    report_startup = settings.get("reportStartup", False)
    report_error = settings.get("reportError", False)

    log(
        "Telegram settings "
        f"reportStartup={report_startup} reportError={report_error} "
        f"token={mask_secret(bot_token)} chatId={'set' if chat_id else 'missing'}"
    )

    if bot_token and chat_id and report_startup:
        try:
            startup_msg = f"{deviceName} đã kết nối"
            send_telegram_message(bot_token, chat_id, startup_msg)
            log(f"Sent startup Telegram notification for {deviceName}")
        except Exception as e:
            log(f"Failed to send startup Telegram notification: {e}")
    elif report_startup:
        missing_fields = []
        if not bot_token:
            missing_fields.append("telegramBotToken")
        if not chat_id:
            missing_fields.append("telegramChatId")
        log(
            "Skipped startup Telegram notification because required setting(s) are missing: "
            + ", ".join(missing_fields)
        )
    else:
        log("Startup Telegram notification is disabled.")

    try:
        # Restore window layout if configured
        window_layout = settings.get("windowLayout")
        if window_layout and isinstance(window_layout, list):
            restore_window_layout(window_layout)
        dry_run = False  # Forced to always run for real
        step_delay = float(settings.get("stepDelaySec", 0))
        start_steps = cast(list[dict[str, Any]], workflow["startSteps"])
        stop_steps = cast(list[dict[str, Any]], workflow["stopSteps"])

        log(f"Starting workflow '{workflow.get('name', 'untitled')}'")
        log(f"Mode: {'dry-run' if dry_run else 'live'}")
        wait_until_schedule(workflow, dry_run)

        repeat = settings.get("repeat", {})
        if repeat.get("enabled"):
            times = repeat.get("times", 0)  # 0 means infinite loop
            interval_ms = repeat.get("intervalMs", 0)
            
            run_count = 0
            while True:
                abort_requested = False
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

        emit_event("workflow_finished", id=root_context["id"], detail="Workflow finished successfully")
        log("Workflow finished successfully")
    except Exception as error:
        emit_event(
            "workflow_failed",
            id=root_context["id"],
            detail=str(error),
            errorType=type(error).__name__,
        )
        if bot_token and chat_id and report_error:
            try:
                error_msg = f"{deviceName} ngắt kết nối vì lỗi trong quá trình flow: {error}"
                send_telegram_message(bot_token, chat_id, error_msg)
                log(f"Sent error Telegram notification for {deviceName}")
            except Exception as te:
                log(f"Failed to send error Telegram notification: {te}")
        raise
    finally:
        # Stop all running intervals
        with intervals_lock:
            if active_intervals:
                log("Cleaning up active intervals...")
                for id_key, item in list(active_intervals.items()):
                    item["stop_event"].set()
                active_intervals.clear()
        pop_context(root_context["id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-json", help="Raw workflow JSON string")
    parser.add_argument("--capture-layout", action="store_true", help="Capture current window positions and sizes and exit")
    args = parser.parse_args()

    if args.capture_layout:
        layout = capture_window_layout()
        print(f"[LAYOUT_JSON]{json.dumps(layout)}")
        return 0

    if not args.workflow_json:
        parser.error("--workflow-json is required unless --capture-layout is specified")

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
