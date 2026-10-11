param([switch]$Lan, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$runtimePython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.desktop-deps') + ';' + (Join-Path $PSScriptRoot '.venv/Lib/site-packages') + ';' + $PSScriptRoot
Set-Location -LiteralPath $PSScriptRoot
if ($Lan) { & $runtimePython -m tools.mobile_workspace --lan --port $Port }
else { & $runtimePython -m tools.mobile_workspace --port $Port }
