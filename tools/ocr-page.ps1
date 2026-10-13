# P0 local OCR of this project's rendered source page; no remote calls/install.
param([Parameter(Mandatory=$true)][string]$ImagePath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../outputs/p0/documents'))
$taskImage = (Resolve-Path -LiteralPath $ImagePath).Path
if (-not $taskImage.StartsWith($taskRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Only rendered source pages under outputs/p0/documents can be OCRed'
}
$taskItem = Get-Item -LiteralPath $taskImage
if ($taskItem.Length -gt 16777216 -or $taskItem.Extension -ne '.png') {
    throw 'PNG OCR input exceeds bounded scope'
}
$taskAncestor = $taskItem
while ($null -ne $taskAncestor) {
    if (($taskAncestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'OCR input cannot traverse a reparse point'
    }
    if ($taskAncestor -is [IO.FileInfo]) {
        $taskAncestor = $taskAncestor.Directory
    } else {
        $taskAncestor = $taskAncestor.Parent
    }
}
$taskReceiptPath = [IO.Path]::ChangeExtension($taskImage, '.json')
$taskReceipt = Get-Content -Raw -LiteralPath $taskReceiptPath | ConvertFrom-Json
$taskImageHash = (Get-FileHash -LiteralPath $taskImage -Algorithm SHA256).Hash.ToLowerInvariant()
if ($taskImageHash -ne $taskReceipt.image_sha256) { throw 'Rendered image changed' }
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] > $null
[Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType=WindowsRuntime] > $null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] > $null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime] > $null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] > $null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime] > $null
$taskAsTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Wait-TaskOcrOperation($Operation, [Type]$ResultType) {
    $taskPending = $taskAsTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    if (-not $taskPending.Wait(15000)) { throw 'Bounded OCR operation timed out' }
    return $taskPending.Result
}
$taskStream = $null
$taskBitmap = $null
try {
    $taskFile = Wait-TaskOcrOperation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($taskImage)) ([Windows.Storage.StorageFile])
    $taskStream = Wait-TaskOcrOperation ($taskFile.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
    $taskDecoder = Wait-TaskOcrOperation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($taskStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $taskBitmap = Wait-TaskOcrOperation ($taskDecoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $taskEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $taskEngine) { throw 'No local OCR engine for current installed languages' }
    if ($taskBitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or
        $taskBitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) {
        throw 'Image exceeds native OCR dimension budget'
    }
    $taskResult = Wait-TaskOcrOperation ($taskEngine.RecognizeAsync($taskBitmap)) ([Windows.Media.Ocr.OcrResult])
    $taskLines = @($taskResult.Lines | ForEach-Object { $_.Text })
    $taskReport = [ordered]@{
        source_sha256=$taskReceipt.source_sha256; page=$taskReceipt.page
        image_sha256=$taskImageHash; language=$taskEngine.RecognizerLanguage.LanguageTag
        lines=$taskLines; status='ocr-extracted-not-read'; visual_verified=$false
        boundary='Local OCR is auxiliary text, not reading, factual or visual verification'
    }
    $taskOutput = [IO.Path]::ChangeExtension($taskImage, '.ocr.json')
    [IO.File]::WriteAllText($taskOutput, ($taskReport | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
    [ordered]@{page=$taskReceipt.page;ocr_path=$taskOutput;lines=$taskLines.Count;language=$taskEngine.RecognizerLanguage.LanguageTag} | ConvertTo-Json -Compress
} finally {
    if ($null -ne $taskBitmap) { $taskBitmap.Dispose() }
    if ($null -ne $taskStream) { $taskStream.Dispose() }
}
