# Install the RTX 5090 tray indicator, background guard and terminal dashboard for the current user.
# No admin rights needed. Run:  powershell -ExecutionPolicy Bypass -File install.ps1
param([switch]$NoStart)
$ErrorActionPreference = 'Stop'
$src  = $PSScriptRoot
$home_ = Join-Path $env:LOCALAPPDATA 'rtx5090-monitor'
$app  = Join-Path $home_ 'app'
$run  = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'RTX 5090 Monitor'

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw 'Python 3.9+ not found in PATH. Install it from python.org (tick "Add to PATH").' }
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { throw "pythonw.exe not found next to $py" }

Write-Host 'Installing Python packages (pystray, Pillow)...'
& $py -m pip install --user --quiet --disable-pip-version-check -r (Join-Path $src 'requirements.txt')
if ($LASTEXITCODE) { throw 'pip install failed' }

Write-Host 'Stopping running copies...'
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -like "*$app*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

New-Item -ItemType Directory -Force $app | Out-Null
Copy-Item (Join-Path $src '*.py'), (Join-Path $src '*.pyw') $app -Force
$cfg = Join-Path $home_ 'config.json'
if (-not (Test-Path $cfg)) {
  # Only the keys people usually change; everything else uses the built-in defaults.
  @{ check_every_s = 15; auto_shutdown = $true; shutdown_delay_s = 30; comfyui = '' } |
    ConvertTo-Json | Set-Content -Encoding utf8 $cfg
}

Write-Host 'Registering autostart (guard + indicator start at sign-in)...'
Set-ItemProperty $run 'RTX5090 astral-guard'  "`"$pyw`" `"$app\astral-guard.py`" --daemon"
Set-ItemProperty $run 'RTX5090 GPU indicator' "`"$pyw`" `"$app\gpu-indicator.pyw`""

Write-Host 'Creating Start menu shortcuts...'
New-Item -ItemType Directory -Force $menu | Out-Null
$sh = New-Object -ComObject WScript.Shell
foreach ($s in @(
    @{ n = 'GPU Monitor';   t = $py;  a = "`"$app\gpu-monitor.py`"" },
    @{ n = 'GPU Indicator'; t = $pyw; a = "`"$app\gpu-indicator.pyw`"" },
    @{ n = 'Guard log';     t = 'powershell.exe'; a = "-NoProfile -NoExit -Command Get-Content -Wait -Tail 50 -LiteralPath '$home_\guard.log'" })) {
  $l = $sh.CreateShortcut((Join-Path $menu "$($s.n).lnk")); $l.TargetPath = $s.t; $l.Arguments = $s.a
  $l.WorkingDirectory = $app; $l.Save()
}

if (-not (Get-Process HWiNFO64 -ErrorAction SilentlyContinue)) {
  Write-Warning 'HWiNFO64 is not running - per-pin data will show as unavailable. See windows\README.md, "HWiNFO setup".'
}
if (-not $NoStart) {
  Start-Process $pyw -ArgumentList "`"$app\astral-guard.py`"", '--daemon'
  Start-Process $pyw -ArgumentList "`"$app\gpu-indicator.pyw`""
}
Write-Host "Installed to $app. The indicator is in the tray (drag it out of the overflow ^ to keep it visible)."
Write-Host "Check the pin mapping any time with:  python `"$app\astral-guard.py`" --list-sensors"
