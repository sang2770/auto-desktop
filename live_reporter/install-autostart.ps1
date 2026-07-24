[CmdletBinding()]
param(
    [string]$BotToken = "",
    [string]$ChatId = "",
    [alias('machine-name')]
    [string]$MachineName = "",
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$DailyReportTime = "23:55",
    [int]$PostSuccessDelaySeconds = 120,
    [int]$ScanIntervalSeconds = 15,
    [switch]$SendScreenshot,
    [alias('reset-state')]
    [switch]$ResetState
)

$ErrorActionPreference = "Stop"
$TaskName = "AutoDesktop-TikTokLiveReporter"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ReporterScript = Join-Path $ScriptDir "live_reporter.py"
$RuntimeDir = Join-Path $env:LOCALAPPDATA "AutoDesktopLiveReporter"
$ConfigPath = Join-Path $RuntimeDir "config.json"
$StatePath = Join-Path $RuntimeDir "state.json"
$LogPath = Join-Path $RuntimeDir "live-reporter.log"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$InstallLogPath = Join-Path $ScriptDir "install-live-reporter.log"

# Tu nang quyen khi chay truc tiep file PS1. File CMD cung lam viec nay de
# double-click la du, nhung giu doan nay de lenh PowerShell thu cong van an toan.
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentPrincipal = New-Object Security.Principal.WindowsPrincipal($CurrentIdentity)
if (-not $CurrentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Dang yeu cau quyen Administrator..."
    try {
        Remove-Item -LiteralPath $InstallLogPath -Force -ErrorAction SilentlyContinue
        # EncodedCommand tranh loi tach dau nhay khi duong dan co khoang trang
        # hoac ky tu dac biet.
        $EscapedScriptPath = $MyInvocation.MyCommand.Path.Replace("'", "''")
        $ElevationCommand = "& '$EscapedScriptPath'"
        $EncodedCommand = [Convert]::ToBase64String(
            [Text.Encoding]::Unicode.GetBytes($ElevationCommand)
        )
        $ElevatedProcess = Start-Process powershell.exe `
            -Verb RunAs `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $EncodedCommand" `
            -Wait `
            -PassThru
        if ($ElevatedProcess.ExitCode -ne 0 -and -not (Test-Path -LiteralPath $InstallLogPath)) {
            [IO.File]::WriteAllText(
                $InstallLogPath,
                "PowerShell Administrator da thoat voi ma loi $($ElevatedProcess.ExitCode).",
                (New-Object Text.UTF8Encoding($false))
            )
        }
        exit $ElevatedProcess.ExitCode
    }
    catch {
        $ElevationError = "Khong mo duoc PowerShell Administrator: $($_.Exception.Message)"
        Write-Host $ElevationError -ForegroundColor Red
        try {
            [IO.File]::WriteAllText(
                $InstallLogPath,
                $ElevationError,
                (New-Object Text.UTF8Encoding($false))
            )
        } catch {}
        exit 1
    }
}

# Cua so PowerShell nang quyen co the dong sau khi loi. Luu toan bo output de
# setup-live-reporter.cmd co the hien lai nguyen nhan trong cua so ban dau.
try {
    Start-Transcript -LiteralPath $InstallLogPath -Force | Out-Null
}
catch {
    Write-Warning "Khong tao duoc install log: $($_.Exception.Message)"
}

trap {
    $FailureMessage = $_.Exception.Message
    Write-Host ""
    Write-Host "CAI DAT THAT BAI: $FailureMessage" -ForegroundColor Red
    Write-Host "Chi tiet log: $InstallLogPath" -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

Write-Host "[1/7] Go task va tien trinh cu neu co..."
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Task co the da bi xoa trong khi pythonw van dang thoat. Chi dung dung tien
# trinh co command line tro den live_reporter.py, khong anh huong Python khac.
$ReporterProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -in @("python.exe", "pythonw.exe") -and
    $_.CommandLine -and
    $_.CommandLine.IndexOf("live_reporter.py", [StringComparison]::OrdinalIgnoreCase) -ge 0
}
foreach ($Process in $ReporterProcesses) {
    Write-Host "Dung reporter PID $($Process.ProcessId)..."
    Stop-Process -Id $Process.ProcessId -Force -ErrorAction SilentlyContinue
}

function Read-SecretText {
    param([string]$Prompt)
    $Secure = Read-Host $Prompt -AsSecureString
    $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    }
}

Write-Host "[2/7] Tao/kiem tra moi truong Python .venv..."
if (-not (Test-Path -LiteralPath $Python) -or -not (Test-Path -LiteralPath $Pythonw)) {
    $SystemPython = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($SystemPython) {
        & $SystemPython.Source -3 -m venv (Join-Path $ProjectRoot ".venv")
    }
    else {
        $SystemPython = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $SystemPython) {
            throw "Khong tim thay Python 3. Hay cai Python 3 (kem Python Launcher) roi chay lai."
        }
        & $SystemPython.Source -m venv (Join-Path $ProjectRoot ".venv")
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Python)) {
        throw "Khong tao duoc .venv."
    }
}

Write-Host "[3/7] Tu dong cai/kiem tra thu vien Python..."

# Python co the ghi Traceback/canh bao vao stderr. PowerShell 5.1 se bien
# stderr thanh loi dung script khi ErrorActionPreference dang la Stop.
$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

try {
    & $Python -c "import PIL, paddleocr, win32gui" 2>$null
    $ImportExitCode = $LASTEXITCODE

    if ($ImportExitCode -ne 0) {
        Write-Host "Thieu thu vien Python (Pillow, PaddleOCR, pywin32), dang cai truoc..." -ForegroundColor Yellow

        & $Python -m pip install --upgrade pip
        $PipUpgradeExitCode = $LASTEXITCODE
        if ($PipUpgradeExitCode -ne 0) {
            throw "Khong nang cap duoc pip. Exit code: $PipUpgradeExitCode"
        }

        # Cài đặt các thư viện cần thiết cho Live Reporter
        & $Python -m pip install --upgrade Pillow paddleocr pywin32
        $PipInstallExitCode = $LASTEXITCODE
        if ($PipInstallExitCode -ne 0) {
            throw "Khong cai duoc Pillow, paddleocr hoac pywin32. Exit code: $PipInstallExitCode"
        }

        & $Python -c "import PIL, pytesseract, win32gui; print('Python dependencies OK')"
        $VerifyExitCode = $LASTEXITCODE
        if ($VerifyExitCode -ne 0) {
            throw "Da chay pip install nhung van khong import duoc thu vien Python."
        }
    }
    else {
        Write-Host "Cac thu vien Python da san sang." -ForegroundColor Green
    }
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

Write-Host "[4/7] Ghi de config bang config.example.json..."
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
if ($ResetState) {
    Write-Host "Reset bien dem va xoa du lieu phien theo yeu cau..."
    & $Python $ReporterScript --reset-state --state $StatePath
}
$TemplatePath = Join-Path $ScriptDir "config.example.json"
if (-not (Test-Path -LiteralPath $TemplatePath)) {
    throw "Khong tim thay file config.example.json"
}
$Config = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8 | ConvertFrom-Json

# Lay Bot Token & Chat ID (uu tien param truyen vao, neu khong co thi lay trong config.example.json)
if (-not $BotToken) {
    $BotToken = $Config.telegram_bot_token
}
if (-not $ChatId) {
    $ChatId = $Config.telegram_chat_id
}

if (-not $BotToken -or $BotToken -eq "DIEN_BOT_TOKEN") {
    throw "Chua dien Telegram Bot Token vao file config.example.json (truong 'telegram_bot_token')."
}
if (-not $ChatId -or $ChatId -eq "DIEN_CHAT_ID") {
    throw "Chua dien Telegram Chat ID vao file config.example.json (truong 'telegram_chat_id')."
}

$Config.telegram_bot_token = $BotToken
$Config.telegram_chat_id = $ChatId

# Chi gán MachineName neu truyen qua parameter hoac trong config.example.json dang rong
if ($MachineName) {
    if ($Config.PSObject.Properties.Name -contains "machine_name") {
        $Config.machine_name = $MachineName
    } else {
        $Config | Add-Member -NotePropertyName "machine_name" -NotePropertyValue $MachineName -Force
    }
} elseif (-not $Config.machine_name) {
    $Config.machine_name = $env:COMPUTERNAME
}

# Chi ghi de tu switch/parameter neu nguoi dung truyen tham so khac mac dinh
if ($PSBoundParameters.ContainsKey('DailyReportTime')) {
    $Config.daily_report_time = $DailyReportTime
}
if ($PSBoundParameters.ContainsKey('SendScreenshot')) {
    $Config.send_screenshot = [bool]$SendScreenshot
}
if ($PSBoundParameters.ContainsKey('PostSuccessDelaySeconds')) {
    $Config.post_success_delay_seconds = $PostSuccessDelaySeconds
}
if ($PSBoundParameters.ContainsKey('ScanIntervalSeconds')) {
    $Config.scan_interval_seconds = $ScanIntervalSeconds
}

Write-Host "[5/7] Đảm bảo PaddleOCR đã được cài đặt..."
# PaddleOCR sẽ được cài đặt trong bước 2/7 (Install-PythonDependencies)
$Config.tesseract_cmd = ""
$ConfigJson = $Config | ConvertTo-Json -Depth 10
$Utf8NoBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText($ConfigPath, $ConfigJson, $Utf8NoBom)

# LocalAppData da thuoc user hien tai; bo quyen ke thua neu he thong cho phep.
try {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $Acl = Get-Acl -LiteralPath $ConfigPath
    $Acl.SetAccessRuleProtection($true, $false)
    $Rule = New-Object Security.AccessControl.FileSystemAccessRule($Identity, "FullControl", "Allow")
    $Acl.SetAccessRule($Rule)
    Set-Acl -LiteralPath $ConfigPath -AclObject $Acl
}
catch {
    Write-Warning "Khong the gioi han ACL config: $($_.Exception.Message)"
}


Write-Host "[6/7] Gui tin nhan Telegram thu..."
& $Python $ReporterScript --config $ConfigPath --test-telegram
if ($LASTEXITCODE -ne 0) {
    throw "Telegram test that bai. Kiem tra Bot Token, Chat ID va viec da nhan Start trong bot."
}

Write-Host "[7/7] Dang ky Task Scheduler khi dang nhap Windows..."
$Arguments = '"{0}" --config "{1}" --state "{2}" --log "{3}"' -f $ReporterScript, $ConfigPath, $StatePath, $LogPath
$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument $Arguments -WorkingDirectory $ProjectRoot
$UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "OCR tam tinh phien TikTok LIVE va gui bao cao Telegram" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host ""
Write-Host "Da cai va khoi dong: $TaskName" -ForegroundColor Green
Write-Host "Config: $ConfigPath"
Write-Host "Log:    $LogPath"
Write-Host "Luu y: TikTok LIVE Studio phai hien tren man hinh (khong minimize) de OCR."
try { Stop-Transcript | Out-Null } catch {}
