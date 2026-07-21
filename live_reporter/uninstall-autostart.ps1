[CmdletBinding()]
param([switch]$PurgeData)

$ErrorActionPreference = "Stop"
$TaskName = "AutoDesktop-TikTokLiveReporter"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Da go Task Scheduler: $TaskName"
}
else {
    Write-Host "Task khong ton tai: $TaskName"
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
