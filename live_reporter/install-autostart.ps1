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

Write-Host "[1/6] Go ban cai cu neu co..."
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
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

if (-not (Test-Path -LiteralPath $Python) -or -not (Test-Path -LiteralPath $Pythonw)) {
    throw "Khong thay .venv. Hay chay: py -3 -m venv .venv"
}

Write-Host "[2/6] Kiem tra thu vien Python..."
& $Python -c "import PIL, pytesseract, win32gui" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install -r (Join-Path $ProjectRoot "runner\requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Khong cai duoc thu vien Python."
    }
}

Write-Host "[3/6] Tao moi cau hinh tu config.example.json..."
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

# Neu da co config.json cu, giu lai Telegram Bot Token, Chat ID va MachineName neu nguoi dung khong truyen tham so
if (Test-Path -LiteralPath $ConfigPath) {
    try {
        $Existing = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $BotToken -and $Existing.telegram_bot_token -and $Existing.telegram_bot_token -ne "DIEN_BOT_TOKEN") {
            $BotToken = $Existing.telegram_bot_token
        }
        if (-not $ChatId -and $Existing.telegram_chat_id -and $Existing.telegram_chat_id -ne "DIEN_CHAT_ID") {
            $ChatId = $Existing.telegram_chat_id
        }
        if (-not $MachineName -and $Existing.machine_name) {
            $MachineName = $Existing.machine_name
        }
    } catch {
        Write-Warning "Khong doc duoc config cu, se reset hoan toan tu template."
    }
}

if (-not $BotToken) {
    $BotToken = Read-SecretText "Nhap Telegram Bot Token"
}
if (-not $ChatId) {
    $ChatId = Read-Host "Nhap Telegram Chat ID"
}
if (-not $BotToken -or -not $ChatId) {
    throw "Bot Token va Chat ID khong duoc de trong."
}

$Config.telegram_bot_token = $BotToken
$Config.telegram_chat_id = $ChatId
if (-not $MachineName) {
    $MachineName = $env:COMPUTERNAME
}
if ($Config.PSObject.Properties.Name -contains "machine_name") {
    $Config.machine_name = $MachineName
} else {
    $Config | Add-Member -NotePropertyName "machine_name" -NotePropertyValue $MachineName -Force
}
$Config.daily_report_time = $DailyReportTime
$Config.send_screenshot = [bool]$SendScreenshot
if ($PostSuccessDelaySeconds -gt 0) {
    $Config.post_success_delay_seconds = $PostSuccessDelaySeconds
}
if ($ScanIntervalSeconds -gt 0) {
    $Config.scan_interval_seconds = $ScanIntervalSeconds
}

Write-Host "[4/6] Tim Tesseract OCR..."
$TesseractCandidates = @(
    (Get-Command tesseract.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $env:ProgramFiles "Tesseract-OCR\tesseract.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Tesseract-OCR\tesseract.exe"),
    (Join-Path $env:LOCALAPPDATA "Tesseract-OCR\tesseract.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

if (-not $TesseractCandidates) {
    throw @"
Khong tim thay Tesseract OCR.
Hay cai Tesseract OCR cho Windows, chon them English language data, roi chay lai script nay.
Trang tai duoc du an dang tham chieu: https://github.com/UB-Mannheim/tesseract/wiki
"@
}
$Config.tesseract_cmd = [string]$TesseractCandidates[0]
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


Write-Host "[5/6] Gui tin nhan Telegram thu..."
& $Python $ReporterScript --config $ConfigPath --test-telegram
if ($LASTEXITCODE -ne 0) {
    throw "Telegram test that bai. Kiem tra Bot Token, Chat ID va viec da nhan Start trong bot."
}

Write-Host "[6/6] Dang ky Task Scheduler khi dang nhap Windows..."
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
