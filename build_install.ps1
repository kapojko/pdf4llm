# build_install.ps1 - build the pdf4llm CLI and install it to C:\Programs\Util
# Python + uv equivalent of pinmapcheck's `go build`: `uv tool install` creates an
# isolated environment and a `pdf4llm` command shim on PATH.
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
try {
    Write-Host "Installing pdf4llm via `uv tool install` ..."
    uv tool install --force .
    if ($LASTEXITCODE -ne 0) {
        throw "uv tool install failed"
    }

    # `uv tool` installs the shim into its managed bin dir. Ask uv where that
    # is (historically %APPDATA%\Python\Scripts, now usually %USERPROFILE%\.local\bin).
    $uvBin = (& uv tool dir --bin).Trim()
    $shim  = Join-Path $uvBin "pdf4llm.exe"
    if (-not (Test-Path $shim)) {
        throw "Shim not found at $shim — uv tool dir --bin is wrong?"
    }

    $dest = "C:\Programs\Util"
    if (-not (Test-Path $dest)) {
        New-Item -ItemType Directory -Path $dest | Out-Null
    }
    if (Test-Path $shim) {
        Copy-Item -Path $shim -Destination (Join-Path $dest "pdf4llm.exe") -Force
        Write-Host "Installed pdf4llm.exe to $dest"
    }
}
finally {
    Pop-Location
}
