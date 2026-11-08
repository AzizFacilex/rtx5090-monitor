# Remove the RTX 5090 indicator and guard. Keeps config.json and guard.log unless -Purge is given.
param([switch]$Purge)
$home_ = Join-Path $env:LOCALAPPDATA 'rtx5090-monitor'
$app   = Join-Path $home_ 'app'
$run   = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'

Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -like "*$app*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-ItemProperty $run 'RTX5090 astral-guard', 'RTX5090 GPU indicator' -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'RTX 5090 Monitor') -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $app -Recurse -Force -ErrorAction SilentlyContinue
if ($Purge) { Remove-Item $home_ -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host 'Removed.' $(if (-not $Purge) { "Config and log kept in $home_ (use -Purge to delete)." })
