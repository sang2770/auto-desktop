# Auto Desktop

MVP desktop app for screen automation workflows such as scheduled TikTok Studio live start/stop flows.

## Stack

- Electron + React + TypeScript for the desktop UI
- Python runner for screen automation actions
- JSON workflows for user-defined steps

## Run

```bash
npm install
npm run dev
```

## Build Windows `.exe`

Download: https://github.com/UB-Mannheim/tesseract/wiki
This project now supports packaging a Windows installer with Electron and bundling the Python runner as `automation_runner.exe`.

### Build machine requirements

- Windows 10/11 x64
- Node.js 18+ and npm
- Python 3.11+ with `pip`
- If you use OCR steps like `check_text`: install Tesseract OCR and add it to `PATH`

### One-time setup on the Windows build machine

```powershell
npm install
py -3 -m pip install -r runner\requirements-build.txt
```

### Create the installer

```powershell
npm run dist:win
```

Output:

- Installer: `release\Auto-Desktop-Setup-0.1.0.exe`
- Unpacked app for testing: use `npm run pack:win`

### What gets bundled

- Electron app UI
- `automation_runner.exe` built from `runner/automation_runner.py`

### Important runtime notes for client machines

- Mouse/keyboard automation still requires OS permissions such as Accessibility / administrator allowances depending on the target app.
- OCR-based steps still need Tesseract installed on the client machine unless you later choose to bundle Tesseract separately.
- Building the Windows `.exe` should be done on Windows because `PyInstaller` builds for the current OS.

## Current MVP

- Edit a workflow as JSON
- Save and reopen workflow files
- Run the workflow through a Python runner
- Separate `startSteps` and `stopSteps` for start/stop live flows
- Support step types: `launch_app`, `wait`, `click`, `wait_for_image`, `check_text`
- Dry-run mode by default so you can test logic without clicking the real screen

## Next recommended additions

- Screen recorder tool to capture coordinates and image templates
- Real scheduler service for start/stop triggers
- Window targeting and focusing
- Retry/fallback branches and step conditions
- OCR/image diagnostics with screenshots on failure
