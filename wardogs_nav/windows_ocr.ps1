# Local Windows OCR, isolated from the UI. One JSON request and reply per line.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
$converter = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Wait-Operation($operation, [Type]$resultType) {
    $pending = $converter.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $pending.GetAwaiter().GetResult()
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US'))
while ($null -ne ($line = [Console]::ReadLine())) {
    $stream = $null
    $bitmap = $null
    $memory = $null
    try {
        if ($null -eq $engine) { throw 'Windows 英文文字识别组件未安装；可先使用坐标输入功能' }
        $request = $line | ConvertFrom-Json
        if ($request.op -ne 'recognize') { throw '未知文字识别操作' }
        $memory = [IO.MemoryStream]::new([IO.File]::ReadAllBytes([string]$request.path))
        $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($memory)
        $decoder = Wait-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Wait-Operation ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore)) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Wait-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @($result.Lines | ForEach-Object {
            $words = @($_.Words | ForEach-Object {
                @{text=$_.Text; x=$_.BoundingRect.X; y=$_.BoundingRect.Y;
                  width=$_.BoundingRect.Width; height=$_.BoundingRect.Height}
            })
            @{text=$_.Text; words=$words}
        })
        $reply = @{ok=$true; lines=$lines}
    } catch {
        $reply = @{ok=$false; error=$_.Exception.Message}
    } finally {
        if ($bitmap) { $bitmap.Dispose() }
        if ($stream) { $stream.Dispose() }
        if ($memory) { $memory.Dispose() }
    }
    [Console]::WriteLine(($reply | ConvertTo-Json -Compress -Depth 6))
}
