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
& $python -m PyInstaller --noconfirm --clean --windowed --onedir --distpath $outputRoot --name WardogsNavigator --add-data 'assets;assets' --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineQuick main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败' }
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $packageRoot '使用说明.md') -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination (Join-Path $packageRoot 'THIRD_PARTY_NOTICES.md') -Force
Copy-Item -LiteralPath 'LICENSE' -Destination (Join-Path $packageRoot 'LICENSE') -Force
Copy-Item -LiteralPath 'NOTICE' -Destination (Join-Path $packageRoot 'NOTICE') -Force
Copy-Item -LiteralPath 'assets\sample_minimap.png' -Destination (Join-Path $packageRoot '定位诊断样例.png') -Force
Copy-Item -LiteralPath '启动导航.cmd' -Destination (Join-Path $packageRoot '启动导航.cmd') -Force
$licenseRoot = Join-Path $packageRoot 'licenses'
New-Item -ItemType Directory -Force $licenseRoot | Out-Null
& $python tools\copy_licenses.py $licenseRoot
if ($LASTEXITCODE -ne 0) { throw '第三方许可证收集失败' }
$zipPath = Join-Path $outputRoot 'WardogsNavigator-Windows-x64.zip'
Compress-Archive -Path $packageRoot -DestinationPath $zipPath -Force
Write-Output $zipPath
