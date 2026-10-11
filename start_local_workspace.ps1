$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python'
$runtimePython = Join-Path $runtimeRoot 'pythonw.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) { $runtimePython = Join-Path $runtimeRoot 'python.exe' }
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.desktop-deps') + ';' + (Join-Path $PSScriptRoot '.venv/Lib/site-packages') + ';' + $PSScriptRoot
Set-Location -LiteralPath $PSScriptRoot
& $runtimePython -m tools.local_workspace_gui
