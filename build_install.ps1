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

    # `uv tool` installs the shim into its managed bin dir (on Windows:
    # %APPDATA%\Python\Scripts\pdf4llm.exe). Copy it into the shared util dir.
    $uvBin = Join-Path $env:APPDATA "Python\Scripts"
    $shim  = Join-Path $uvBin "pdf4llm.exe"
    if (-not (Test-Path $shim)) {
        # Fallback: ask uv where tools are installed.
        Write-Warning "Shim not found at $shim — relying on the uv-managed PATH entry."
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
