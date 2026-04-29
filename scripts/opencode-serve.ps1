param([switch]$Stop,[switch]$Restart,[switch]$Help)

if ($Help) {
    Write-Host @"
Usage: .\opencode-serve.ps1 [-Stop] [-Restart] [-Help]

  -Stop     Stop the running server
  -Restart  Restart the server
  -Help     Show this help

Defaults: hostname=0.0.0.0, port=64763
Logs:     %LOCALAPPDATA%\OpenCode\serve-logs
"@
    exit
}

$dir     = "$env:LOCALAPPDATA\OpenCode\serve-logs"
$pidFile = "$dir\serve.pid"
$logOut  = "$dir\serve.log"
$logErr  = "$dir\serve.err"
$port    = 64763

function Stop-Server {
    if (Test-Path $pidFile) {
        $id = Get-Content $pidFile
        Stop-Process -Id $id -ErrorAction SilentlyContinue
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        Write-Host "Stopped (PID: $id)"
    } else {
        Write-Host "Not running"
    }
}

if ($Stop)    { Stop-Server; exit }
if ($Restart) { Stop-Server }

$null = New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue
$opencode = (Get-Command opencode).Source
$proc = Start-Process pwsh `
    -ArgumentList '-NoProfile','-File',"`"$opencode`"",'serve','--hostname','0.0.0.0','--port',$port `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logOut `
    -RedirectStandardError $logErr `
    -PassThru

$proc.Id | Set-Content $pidFile
Write-Host "Started (PID: $($proc.Id)) → http://0.0.0.0:$port"
Write-Host "Logs:   $logOut, $logErr"
Write-Host "Stop:   .\opencode-serve.ps1 -Stop"
Write-Host "Restart: .\opencode-serve.ps1 -Restart"
