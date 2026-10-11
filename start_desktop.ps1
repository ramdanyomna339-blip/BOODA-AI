param(
    [ValidateSet('local', 'local-tools', 'gemini', 'gemini-paid', 'ollama', 'mock', 'openai')]
    [string]$Provider,
    [ValidateSet('balanced', 'fast')]
    [string]$ModelProfile,
    [string]$ProjectId,
    [string]$ClientId,
    [switch]$Console
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimePython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) {
    throw 'Python runtime missing. Install requirements-desktop.txt in your Python environment and run python -m tools.desktop_menu.'
}
$env:PYTHONPATH = (Join-Path $projectRoot '.desktop-deps') + ';' + (Join-Path $projectRoot '.venv/Lib/site-packages')
if ($PSBoundParameters.ContainsKey('Provider')) {
    $env:BOODA_AI_PROVIDER = $Provider
}
if ($PSBoundParameters.ContainsKey('ProjectId')) { $env:BOODA_PROJECT_ID = $ProjectId }
if ($PSBoundParameters.ContainsKey('ClientId')) { $env:BOODA_CLIENT_ID = $ClientId }
if ($PSBoundParameters.ContainsKey('ModelProfile')) {
    $modelFile = if ($ModelProfile -eq 'fast') { 'qwen2.5-0.5b-instruct-q4_k_m.gguf' } else { 'Qwen3-4B-Q2_K.gguf' }
    $selectedModel = Join-Path $projectRoot ('.local-ai-runtime/models/' + $modelFile)
    if (-not (Test-Path -LiteralPath $selectedModel)) { throw 'Selected local model is missing. No automatic download or fallback.' }
    $env:BOODA_LOCAL_MODEL_PATH = $selectedModel
}
Set-Location -LiteralPath $projectRoot
if ($Console) {
    & $runtimePython -m tools.desktop_menu
} else {
    & $runtimePython -m tools.arabic_desktop
}
