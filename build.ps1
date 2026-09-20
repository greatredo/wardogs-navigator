param([string]$OutputDirectory = 'dist', [string]$PythonExecutable = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$python = if ($PythonExecutable) { $PythonExecutable } else { Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'build\pyinstaller-cache'
$distRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'dist'))
$outputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) { [IO.Path]::GetFullPath($OutputDirectory) } else { [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $OutputDirectory)) }
if ($outputRoot -ne $distRoot -and -not $outputRoot.StartsWith($distRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '构建输出必须位于本项目 dist 目录内' }
$packageRoot = Join-Path $outputRoot 'WardogsNavigator'
if (-not (Test-Path -LiteralPath $python)) { throw '请先创建 .venv 并安装 requirements.txt' }
# Foreign tools on PATH can supply incompatible DLLs with Windows system names
# (notably icuuc.dll). Resolve native dependencies only from Python and Windows.
$pythonBase = & $python -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw '无法确定 Python 运行环境' }
$previousBuildPath = $env:PATH
try {
    $env:PATH = @((Split-Path -Parent $python), $pythonBase,
        (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join [IO.Path]::PathSeparator
    & $python tools\build_frozen.py --noconfirm --clean --windowed --onedir --distpath $outputRoot --name WardogsNavigator --add-data 'assets;assets' --add-data 'wardogs_audio/assets;wardogs_audio/assets' --add-data 'wardogs_audio/windows_speech.ps1;wardogs_audio' --exclude-module PySide6.QtTextToSpeech --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineQuick main.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败' }
} finally {
    $env:PATH = $previousBuildPath
}
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $packageRoot '使用说明.md') -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination (Join-Path $packageRoot 'THIRD_PARTY_NOTICES.md') -Force
Copy-Item -LiteralPath 'LICENSE' -Destination (Join-Path $packageRoot 'LICENSE') -Force
Copy-Item -LiteralPath 'NOTICE' -Destination (Join-Path $packageRoot 'NOTICE') -Force
Copy-Item -LiteralPath 'assets\sample_minimap.png' -Destination (Join-Path $packageRoot '定位诊断样例.png') -Force
Copy-Item -LiteralPath '启动导航.cmd' -Destination (Join-Path $packageRoot '启动导航.cmd') -Force
$guideRoot = Join-Path $packageRoot 'community'
New-Item -ItemType Directory -Force $guideRoot | Out-Null
Copy-Item -LiteralPath 'community\新手投稿图文教程.md','community\新手投稿纯文字教程.txt' -Destination $guideRoot -Force
Copy-Item -LiteralPath 'community\guide-images' -Destination $guideRoot -Recurse -Force
$licenseRoot = Join-Path $packageRoot 'licenses'
New-Item -ItemType Directory -Force $licenseRoot | Out-Null
& $python tools\copy_licenses.py $licenseRoot
if ($LASTEXITCODE -ne 0) { throw '第三方许可证收集失败' }
$zipPath = Join-Path $outputRoot 'WardogsNavigator-Windows-x64.zip'
Compress-Archive -Path $packageRoot -DestinationPath $zipPath -Force
Write-Output $zipPath
