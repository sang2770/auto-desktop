#!/usr/bin/env python3

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


def perform_click(pyautogui: Any, x: Any, y: Any, button: str = "left") -> tuple[int, int, str]:
    screen_x = to_screen_int(x)
    screen_y = to_screen_int(y)
    frontmost_before = get_frontmost_app_name()
    darwin_success, backend = perform_darwin_click(screen_x, screen_y, click_count=1, button=button)
    if not darwin_success:
        pyautogui.moveTo(screen_x, screen_y)
        pyautogui.mouseDown(x=screen_x, y=screen_y, button=button)
        time.sleep(0.07)
        pyautogui.mouseUp(x=screen_x, y=screen_y, button=button)
        backend = f"pyautogui-fallback:{backend}"
    frontmost_after = get_frontmost_app_name()
    if should_repeat_after_focus_change(frontmost_before, frontmost_after):
        log(f"Focus changed during click: {frontmost_before} -> {frontmost_after}. Repeating click at same point.")
        time.sleep(0.2)
        retry_success, retry_backend = perform_darwin_click(screen_x, screen_y, click_count=1, button=button)
        if not retry_success:
            pyautogui.moveTo(screen_x, screen_y)
            pyautogui.mouseDown(x=screen_x, y=screen_y, button=button)
            time.sleep(0.07)
            pyautogui.mouseUp(x=screen_x, y=screen_y, button=button)
            retry_backend = f"pyautogui-fallback:{retry_backend}"
        backend = f"{backend}+focus-retry:{retry_backend}"
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


def execute_step_list(steps: list[dict[str, Any]], dry_run: bool, label: str, step_delay: float = 0.0) -> None:
    log(f"Running {label} sequence with {len(steps)} step(s)")
    for index, step in enumerate(steps, start=1):
        step_type = step["type"]
        log(f"Step {index}/{len(steps)}: {step.get('name', step_type)} [{step_type}]")

        if step_type == "launch_app":
            run_command(step["command"], dry_run)
        elif step_type == "click":
            step_click(step, dry_run)
        elif step_type == "double_click":
            step_double_click(step, dry_run)
        elif step_type == "wait":
            step_wait(step)
        elif step_type == "wait_for_image":
            step_wait_for_image(step, dry_run)
        elif step_type == "check_text":
            step_check_text(step, dry_run)
        elif step_type == "conditional":
            step_conditional(step, dry_run)
        else:
            raise ValueError(f"Unsupported step type: {step_type}")

        if step_delay > 0 and index < len(steps):
            log(f"Waiting {step_delay}s between steps...")
            time.sleep(step_delay)



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
