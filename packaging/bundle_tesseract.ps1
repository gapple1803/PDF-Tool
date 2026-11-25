# Copy a Tesseract install (UB Mannheim build, e.g. from `choco install tesseract`)
# into the app folder, keeping only the engine, its DLLs and the chosen languages.
#   ./packaging/bundle_tesseract.ps1 -Source "C:\Program Files\Tesseract-OCR" -Dest dist\PDFParser\tesseract
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Dest,
    [string[]]$Languages = @("eng", "osd")
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path (Join-Path $Source "tesseract.exe"))) { throw "tesseract.exe not found in $Source" }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# Engine + runtime DLLs (training tools, uninstaller and docs are left out)
Copy-Item (Join-Path $Source "tesseract.exe") $Dest
Copy-Item (Join-Path $Source "*.dll") $Dest

# Language data
$tessdata = Join-Path $Dest "tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null
foreach ($lang in $Languages) {
    Copy-Item (Join-Path $Source "tessdata\$lang.traineddata") $tessdata
}
foreach ($dir in "configs", "tessconfigs") {
    $p = Join-Path $Source "tessdata\$dir"
    if (Test-Path $p) { Copy-Item $p $tessdata -Recurse }
}

# Licence texts shipped with the install, if any
Get-ChildItem $Source -File | Where-Object { $_.Name -match '(?i)licen[cs]e|copying|notice' } |
    Copy-Item -Destination $Dest

& (Join-Path $Dest "tesseract.exe") --version
& (Join-Path $Dest "tesseract.exe") --tessdata-dir $tessdata --list-langs
if ($LASTEXITCODE -ne 0) { throw "bundled tesseract does not run" }
$size = (Get-ChildItem $Dest -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Bundled Tesseract: {0:N1} MB" -f $size)
