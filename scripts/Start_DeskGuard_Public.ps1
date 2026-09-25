$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$zrok = Join-Path $projectRoot '.zrok\zrok2.exe'
$shareLog = Join-Path $projectRoot 'logs\zrok-share.log'
$shareError = Join-Path $projectRoot 'logs\zrok-share-error.log'
if (-not (Test-Path $zrok)) {
    throw "zrok client not found: $zrok"
}

$dashboard = Get-NetTCPConnection -LocalPort 5151 -State Listen -ErrorAction SilentlyContinue
if (-not $dashboard) {
    Start-Process -FilePath 'python' -ArgumentList 'src\dashboard.py' -WorkingDirectory $projectRoot -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

$existingZrok = Get-Process -Name 'zrok2' -ErrorAction SilentlyContinue
if (-not $existingZrok) {
    New-Item -ItemType Directory -Force (Join-Path $projectRoot 'logs') | Out-Null
    # A stale machine proxy can make zrok report DNS failures or leave the
    # reserved public name attached to a dead backend. Do not pass proxy
    # settings through to the tunnel client.
    $zrokStart = New-Object System.Diagnostics.ProcessStartInfo
    $zrokStart.FileName = $zrok
    $zrokStart.WorkingDirectory = $projectRoot
    $zrokStart.Arguments = 'share public http://127.0.0.1:5151 --headless --force-local --name-selection public:deskguard'
    $zrokStart.UseShellExecute = $false
    $zrokStart.CreateNoWindow = $true
    $zrokStart.RedirectStandardOutput = $true
    $zrokStart.RedirectStandardError = $true
    foreach ($proxyName in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')) {
        $zrokStart.Environment.Remove($proxyName)
    }
    $zrokProcess = New-Object System.Diagnostics.Process
    $zrokProcess.StartInfo = $zrokStart
    $null = $zrokProcess.Start()
    $zrokProcess.BeginOutputReadLine()
    $zrokProcess.BeginErrorReadLine()
    $zrokProcess.add_OutputDataReceived({ param($sender, $event) if ($null -ne $event.Data) { Add-Content -LiteralPath $shareLog -Value $event.Data } })
    $zrokProcess.add_ErrorDataReceived({ param($sender, $event) if ($null -ne $event.Data) { Add-Content -LiteralPath $shareError -Value $event.Data } })
}
