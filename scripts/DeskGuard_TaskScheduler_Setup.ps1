$ErrorActionPreference = 'Stop'

$appDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $pythonw = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $pythonw) {
    throw 'Python was not found on PATH. Install Python or add it to PATH, then run setup again.'
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user

$tasks = @(
    @{ Name = 'DeskGuardRecorder'; Script = (Join-Path $appDir 'src\deskguard.py') },
    @{ Name = 'DeskGuardWatchdog'; Script = (Join-Path $appDir 'src\watchdog.py') }
)

Write-Host "Registering DeskGuard tasks for $user"
Write-Host "Python: $pythonw"
Write-Host "Working directory: $appDir"

foreach ($item in $tasks) {
    if (-not (Test-Path -LiteralPath $item.Script)) {
        throw "Script not found: $($item.Script)"
    }

    $action = New-ScheduledTaskAction `
        -Execute $pythonw `
        -Argument ('"{0}"' -f $item.Script) `
        -WorkingDirectory $appDir

    Register-ScheduledTask `
        -TaskName $item.Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Description "DeskGuard $($item.Name -replace '^DeskGuard', '')" `
        -Force | Out-Null

    $task = Get-ScheduledTask -TaskName $item.Name
    Write-Host ("  {0}: {1} ({2})" -f $item.Name, $task.State, $task.Principal.UserId)
}

Write-Host ''
Write-Host 'Starting both tasks now...'
foreach ($item in $tasks) {
    Start-ScheduledTask -TaskName $item.Name
}
Start-Sleep -Seconds 3

$failed = $false
foreach ($item in $tasks) {
    $info = Get-ScheduledTaskInfo -TaskName $item.Name
    $task = Get-ScheduledTask -TaskName $item.Name
    Write-Host ("  {0}: state={1}, lastResult={2}, lastRun={3}" -f $item.Name, $task.State, $info.LastTaskResult, $info.LastRunTime)
    if ($info.LastTaskResult -ne 0) { $failed = $true }
}

if ($failed) {
    Write-Warning 'A task reported a non-zero result. Check logs\deskguard_events.log and logs\watchdog_events.log.'
    exit 1
}

Write-Host 'Done. The tasks will run at logon in the interactive user session.'
exit 0
