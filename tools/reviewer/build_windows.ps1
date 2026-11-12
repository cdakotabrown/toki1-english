param(
    [switch]$InstallBuildDependencies,
    [string]$WorkRoot = (Join-Path $env:LOCALAPPDATA 'TokimekiReview-build')
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on Windows with Python 3.10+.' }
# Build on a Windows drive even when the checkout is on a WSL/network share.
$buildRoot = Join-Path $PSScriptRoot '..\..\build\translation-reviewer-windows'
New-Item -ItemType Directory -Force $buildRoot, $WorkRoot | Out-Null
$source = Join-Path $WorkRoot 'source'
New-Item -ItemType Directory -Force $source | Out-Null
$files = @('app.py', 'review_model.py', 'dialogue_editor.py', 'scene_panel.py',
           'packaged_smoke.py', 'scene_assets.py', 'test_review_model.py', 'test_scene_assets.py')
foreach ($file in $files) { Copy-Item (Join-Path $PSScriptRoot $file) $source -Force }
$previousGuiTests = $env:REVIEW_GUI_TESTS
Push-Location $source
try {
    # Use a private build environment, never the project's decompilation venv.
    $venv = Join-Path $WorkRoot 'venv'
    if (!(Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
        & py -3 -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python build environment.' }
    }
    $python = Join-Path $venv 'Scripts\python.exe'
    if ($InstallBuildDependencies) {
        & $python -m pip install 'Pillow>=10,<13' 'pyinstaller>=6,<7'
        if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    }
    $env:REVIEW_GUI_TESTS = '1'
    & $python -m unittest discover -s . -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Reviewer tests failed; packaging stopped.' }
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name TokimekiReview --distpath (Join-Path $WorkRoot 'dist') `
        --workpath (Join-Path $WorkRoot 'work') --specpath $WorkRoot app.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed. Rerun with -InstallBuildDependencies if dependencies are missing.' }
    $exe = Join-Path $WorkRoot 'dist\TokimekiReview.exe'
    $report = Join-Path $WorkRoot 'acceptance.json'
    Remove-Item $report -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $exe -ArgumentList @('--self-test', ('"' + $report + '"')) -PassThru
    if (!$process.WaitForExit(120000)) {
        $process.Kill()
        throw 'Packaged acceptance test timed out.'
    }
    if (!(Test-Path $report)) { throw 'Packaged app failed to write its acceptance report.' }
    $result = Get-Content $report -Raw | ConvertFrom-Json
    if ($process.ExitCode -ne 0 -or !$result.passed -or !$result.frozen) {
        Get-Content $report
        throw 'Packaged Windows acceptance failed.'
    }
    $dist = Join-Path $buildRoot 'dist'
    New-Item -ItemType Directory -Force $dist | Out-Null
    Copy-Item $exe $dist -Force
    Copy-Item $report $buildRoot -Force
    & $python -m pip freeze | Set-Content (Join-Path $buildRoot 'build-dependencies.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not record build dependencies.' }
    (Get-FileHash (Join-Path $dist 'TokimekiReview.exe') -Algorithm SHA256).Hash |
        Set-Content (Join-Path $dist 'TokimekiReview.exe.sha256')
    Write-Host "Built and tested: $dist\TokimekiReview.exe ($($result.checks.Count) acceptance checks)"
    Write-Host 'Distribute sheets, CHARACTER-BIBLE.md and scene assets separately. No game data is embedded.'
} finally {
    $env:REVIEW_GUI_TESTS = $previousGuiTests
    Pop-Location
}
