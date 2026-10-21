# build_install.ps1 - build the pdf4llm CLI and install it to C:\Programs\Util
# Python + uv equivalent of pinmapcheck's `go build`: `uv tool install` creates an
# isolated environment and a `pdf4llm` command shim on PATH.
#
# GPU runtime for the neural layout engine (onnxruntime):
#   default   -> CUDA runtime DLLs (NVIDIA machines), equivalent to the
#                'cuda' extra in pyproject.toml (keep the pins in sync)
#   -DirectML -> onnxruntime-directml (AMD/Intel, incl. Intel XPU on Windows),
#                equivalent to the 'directml' extra. The two conflict — pick one.
# NOTE: `uv tool install` has no --extra flag (uv 0.9.x), so the runtime
# packages are added with --with.
param(
    [switch]$DirectML
)
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
try {
    Write-Host "Installing pdf4llm via `uv tool install` ..."
    $gpuArgs = if ($DirectML) {
        @("--with", "onnxruntime-directml>=1.20")
    } else {
        # keep in sync with the [project.optional-dependencies].cuda pins
        @("--with", "nvidia-cuda-runtime>=13.4,<14",
          "--with", "nvidia-cublas>=13.8.0.4,<13.8.1",
          "--with", "nvidia-cudnn-cu13>=9.10,<10")
    }
    Write-Host "  GPU runtime: $($gpuArgs -join ' ')"
    uv tool install --force . @gpuArgs
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
