<#
DeskGuard kill switch.

  DeskGuard_KillSwitch.bat            -> stop everything, disable auto-start
  DeskGuard_KillSwitch.bat restore    -> re-enable auto-start and start everything

Order matters:
  1. Disable the scheduled tasks first so nothing restarts while we work.
  2. Kill the WATCHDOG before the recorder. If the recorder dies while a lock
     is active, the watchdog calls LockWorkStation() (real Windows lock).
  3. Kill recorder, stop the NSSM dashboard service, kill dashboard + zrok.
  4. Delete heartbeat.json so a stale "locked" heartbeat can never trigger
     the watchdog on a later start.
Processes are found by exe name (dist\*.exe builds) or by command line
matching src\deskguard.py / watchdog.py / dashboard.py (python builds).
Self-elevates to Administrator (needed for schtasks + service control).
#>
param(
    [ValidateSet('kill', 'restore')][string]$Action = 'kill',
    [switch]$NoPause
)

$ErrorActionPreference = 'Continue'

# --- elevate ---------------------------------------------------------------
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', "`"$PSCommandPath`"", '-Action', $Action
    )
    exit
}

$Root    = Split-Path -Parent $PSScriptRoot
$Tasks   = @('DeskGuardWatchdog', 'DeskGuardRecorder', 'DeskGuard Public Share')
$Service = 'DeskGuardDashboard'
$ScriptMap  = @{ Watchdog = 'watchdog'; Recorder = 'deskguard'; Dashboard = 'dashboard' }
$LogDir  = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force $LogDir | Out-Null
$KsLog   = Join-Path $LogDir 'killswitch.log'

function Say($msg, $color = 'Gray') {
    Write-Host $msg -ForegroundColor $color
    Add-Content -LiteralPath $KsLog -Value ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

function Test-Task($name) {
    schtasks /Query /TN $name 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Find-Procs($key) {
    $rx = 'src[\\/]' + $ScriptMap[$key] + '\.py'
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -ieq "DeskGuard$key.exe") -or
        ($_.CommandLine -and $_.Name -match '^(python|pythonw|py)\.exe$' -and $_.CommandLine -match $rx)
    }
}

function Stop-Group($key) {
    $found = @(Find-Procs $key)
    if ($found.Count -eq 0) { Say "  $key : not running"; return }
    foreach ($p in $found) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Say "  $key : killed pid $($p.ProcessId) ($($p.Name))" 'Green'
        } catch {
            Say "  $key : FAILED to kill pid $($p.ProcessId): $($_.Exception.Message)" 'Red'
        }
    }
}

# =============================================================================
if ($Action -eq 'kill') {
    Say '=== DeskGuard KILL SWITCH ===' 'Yellow'

    Say '[1/6] Disabling auto-start tasks (no /End here - see note on watchdog order)'
    foreach ($t in $Tasks) {
        if (Test-Task $t) {
            schtasks /Change /TN $t /DISABLE 2>&1 | Out-Null
            Say "  task '$t' : disabled" 'Green'
        } else { Say "  task '$t' : not found" }
    }

    Say '[2/6] Killing watchdog (must go before the recorder)'
    Stop-Group 'Watchdog'

    Say '[3/6] Killing recorder'
    Stop-Group 'Recorder'

    Say '[4/6] Stopping dashboard service + process'
    $svc = Get-Service -Name $Service -ErrorAction SilentlyContinue
    if ($svc) {
        Set-Service -Name $Service -StartupType Disabled -ErrorAction SilentlyContinue
        if ($svc.Status -ne 'Stopped') {
            Stop-Service -Name $Service -Force -ErrorAction SilentlyContinue
        }
        Say "  service '$Service' : stopped + set to Disabled" 'Green'
    } else { Say "  service '$Service' : not installed" }
    Stop-Group 'Dashboard'

    Say '[5/6] Killing zrok public share'
    $z = Get-Process -Name 'zrok2' -ErrorAction SilentlyContinue |
         Where-Object { $_.Path -and $_.Path -like (Join-Path $Root '.zrok\*') }
    if ($z) {
        $z | ForEach-Object {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            Say "  zrok2 : killed pid $($_.Id)" 'Green'
        }
    } else { Say '  zrok2 : not running' }

    Say '[6/6] Cleanup'
    Get-ChildItem -LiteralPath $LogDir -Filter 'heartbeat.json*' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Say '  heartbeat files removed'
    try {
        Add-Type -Namespace DG -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool ClipCursor(IntPtr r);' -ErrorAction Stop
        [DG.U]::ClipCursor([IntPtr]::Zero) | Out-Null
        Say '  cursor clip released'
    } catch { }

    Start-Sleep -Seconds 1
    $left = @('Watchdog', 'Recorder', 'Dashboard') | ForEach-Object { Find-Procs $_ }
    $port = Get-NetTCPConnection -LocalPort 5151 -State Listen -ErrorAction SilentlyContinue
    if ($left -or $port) {
        Say 'WARNING: something is still alive:' 'Red'
        $left | ForEach-Object { Say "  pid $($_.ProcessId) $($_.Name)" 'Red' }
        if ($port) { Say "  port 5151 still listening (pid $($port.OwningProcess -join ','))" 'Red' }
    } else {
        Say 'DeskGuard is fully stopped. Auto-start is disabled.' 'Green'
        Say "Run:  DeskGuard_KillSwitch.bat restore   to bring it back." 'Yellow'
    }
}

# =============================================================================
if ($Action -eq 'restore') {
    Say '=== DeskGuard RESTORE ===' 'Yellow'
    foreach ($t in $Tasks) {
        if (Test-Task $t) {
            schtasks /Change /TN $t /ENABLE 2>&1 | Out-Null
            Say "  task '$t' : enabled" 'Green'
        }
    }
    $svc = Get-Service -Name $Service -ErrorAction SilentlyContinue
    if ($svc) {
        Set-Service -Name $Service -StartupType Automatic
        Start-Service -Name $Service -ErrorAction SilentlyContinue
        Say "  service '$Service' : Automatic + started" 'Green'
    }
    # recorder first, watchdog second
    foreach ($t in @('DeskGuardRecorder', 'DeskGuardWatchdog', 'DeskGuard Public Share')) {
        if (Test-Task $t) { schtasks /Run /TN $t 2>&1 | Out-Null; Say "  task '$t' : started" 'Green' }
    }
    Say 'Restored. Check logs\deskguard_events.log for "DeskGuard recorder starting".' 'Yellow'
}

if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
