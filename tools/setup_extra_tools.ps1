$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$deps = Join-Path $projectRoot '.desktop-deps'
& $desktopPython -m pip install --target $deps 'playwright==1.63.0' 'arabic-reshaper==3.0.0' 'python-bidi==0.6.7' 'https://github.com/simonflueckiger/tesserocr-windows_build/releases/download/tesserocr-v2.11.0-tesseract-4.1.3/tesserocr-2.11.0-cp312-cp312-win_amd64.whl'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $desktopPython -m pip install --target $deps 'pypdf>=6,<7' 'openpyxl>=3.1,<4' 'defusedxml>=0.7,<1' 'youtube-transcript-api==1.2.4'
if ($LASTEXITCODE -ne 0) { throw 'Document dependency installation failed.' }
$data = Join-Path $projectRoot '.local-ai-runtime/tessdata'
New-Item -ItemType Directory -Force $data | Out-Null
foreach ($language in @('ara', 'eng')) {
    Invoke-WebRequest "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/$language.traineddata" -OutFile (Join-Path $data "$language.traineddata")
}
$env:PYTHONPATH = $deps
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot '.local-ai-runtime/browsers'
& $desktopPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'Browser installation failed.' }
