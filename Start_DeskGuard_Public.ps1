$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$zrok = Join-Path $projectRoot '.zrok\zrok2.exe'
$shareLog = Join-Path $projectRoot 'logs\zrok-share.log'
$shareError = Join-Path $projectRoot 'logs\zrok-share-error.log'
if (-not (Test-Path $zrok)) {
    throw "zrok client not found: $zrok"
}

$dashboard = Get-NetTCPConnection -LocalPort 5151 -State Listen -ErrorAction SilentlyContinue
if (-not $dashboard) {
    Start-Process -FilePath 'python' -ArgumentList 'dashboard.py' -WorkingDirectory $projectRoot -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

$existingZrok = Get-Process -Name 'zrok2' -ErrorAction SilentlyContinue
if (-not $existingZrok) {
    New-Item -ItemType Directory -Force (Join-Path $projectRoot 'logs') | Out-Null
    Start-Process -FilePath $zrok `
        -ArgumentList @('share', 'public', 'http://127.0.0.1:5151', '--headless', '--force-local', '--name-selection', 'public:deskguard') `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $shareLog `
        -RedirectStandardError $shareError
}
