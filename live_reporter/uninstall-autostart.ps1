[CmdletBinding()]
param([switch]$PurgeData)

$ErrorActionPreference = "Stop"
$TaskName = "AutoDesktop-TikTokLiveReporter"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Da go Task Scheduler: $TaskName" -ForegroundColor Green
}
else {
    Write-Host "Task khong ton tai: $TaskName" -ForegroundColor Yellow
}

$ReporterProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -in @("python.exe", "pythonw.exe") -and
    $_.CommandLine -and
    $_.CommandLine.IndexOf("live_reporter.py", [StringComparison]::OrdinalIgnoreCase) -ge 0
}
if ($ReporterProcesses) {
    foreach ($Process in $ReporterProcesses) {
        Stop-Process -Id $Process.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Da dung tien trinh PID: $($Process.ProcessId)" -ForegroundColor Green
    }
}
else {
    Write-Host "Khong co tien trinh live_reporter.py nao dang chay." -ForegroundColor Yellow
}

if ($PurgeData) {
    $RuntimeDir = Join-Path $env:LOCALAPPDATA "AutoDesktopLiveReporter"
    $Resolved = [IO.Path]::GetFullPath($RuntimeDir)
    $ExpectedRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA)
    if ($Resolved.StartsWith($ExpectedRoot, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $Resolved)) {
        Remove-Item -LiteralPath $Resolved -Recurse -Force
        Write-Host "Da xoa config, state va log: $Resolved"
    }
}
