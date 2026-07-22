[CmdletBinding()]
param(
    [string]$BotToken = "",
    [string]$ChatId = "",
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$DailyReportTime = "23:55",
    [int]$PostSuccessDelaySeconds = 120,
    [switch]$SendScreenshot
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

Write-Host "[1/4] Kiem tra thu vien Python..."
& $Python -c "import PIL, pytesseract, win32gui" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install -r (Join-Path $ProjectRoot "runner\requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Khong cai duoc thu vien Python."
    }
}

Write-Host "[2/4] Tao cau hinh rieng trong LocalAppData..."
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
$TemplatePath = Join-Path $ScriptDir "config.example.json"
$Config = Get-Content -LiteralPath $TemplatePath -Raw -Encoding UTF8 | ConvertFrom-Json

if (Test-Path -LiteralPath $ConfigPath) {
    $Existing = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($Property in $Existing.PSObject.Properties) {
        if ($Config.PSObject.Properties.Name -contains $Property.Name) {
            $Config.$($Property.Name) = $Property.Value
        }
    }
}

if (-not $BotToken) {
    if ($Config.telegram_bot_token -and $Config.telegram_bot_token -ne "DIEN_BOT_TOKEN") {
        $BotToken = $Config.telegram_bot_token
    }
    else {
        $BotToken = Read-SecretText "Nhap Telegram Bot Token"
    }
}
if (-not $ChatId) {
    if ($Config.telegram_chat_id -and $Config.telegram_chat_id -ne "DIEN_CHAT_ID") {
        $ChatId = $Config.telegram_chat_id
    }
    else {
        $ChatId = Read-Host "Nhap Telegram Chat ID"
    }
}
if (-not $BotToken -or -not $ChatId) {
    throw "Bot Token va Chat ID khong duoc de trong."
}

$Config.telegram_bot_token = $BotToken
$Config.telegram_chat_id = $ChatId
$Config.daily_report_time = $DailyReportTime
$Config.post_success_delay_seconds = $PostSuccessDelaySeconds
$Config.send_screenshot = [bool]$SendScreenshot

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

Write-Host "[3/4] Gui tin nhan Telegram thu..."
& $Python $ReporterScript --config $ConfigPath --test-telegram
if ($LASTEXITCODE -ne 0) {
    throw "Telegram test that bai. Kiem tra Bot Token, Chat ID va viec da nhan Start trong bot."
}

Write-Host "[4/4] Dang ky Task Scheduler khi dang nhap Windows..."
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
