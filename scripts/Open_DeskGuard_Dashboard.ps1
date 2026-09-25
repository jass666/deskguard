$ErrorActionPreference = 'Stop'

$port = 5151
$localUrl = "http://127.0.0.1:$port/"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Test-Dashboard {
    try {
        $response = Invoke-WebRequest -Uri $localUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

if (-not (Test-Dashboard)) {
    $dashboard = Join-Path $projectRoot 'src\dashboard.py'
    Start-Process -FilePath 'python' -ArgumentList 'src\dashboard.py' -WorkingDirectory $projectRoot -WindowStyle Hidden
}

$deadline = (Get-Date).AddSeconds(15)
while (-not (Test-Dashboard) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Dashboard)) {
    throw "DeskGuard dashboard did not become available at $localUrl"
}

$lanAddresses = @(
    Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike '127.*' -and
            $_.IPAddress -notlike '169.254.*' -and
            $_.AddressState -eq 'Preferred'
        } |
        Sort-Object InterfaceMetric, SkipAsSource
)

Write-Host "DeskGuard dashboard: $localUrl"
if ($lanAddresses.Count -gt 0) {
    Write-Host "LAN address (only works if the dashboard is configured for network access):"
    $lanAddresses | ForEach-Object { Write-Host "  http://$($_.IPAddress):$port/" }
}

Start-Process $localUrl
