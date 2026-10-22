# build_install.ps1 - build the pdf4llm CLI and install it to C:\Programs\Util
# Python + uv equivalent of pinmapcheck's `go build`: `uv tool install` creates an
# isolated environment and a `pdf4llm` command shim on PATH.
#
# GPU runtime for the neural layout engine (onnxruntime):
#   default   -> CUDA runtime DLLs (NVIDIA machines), equivalent to the
#                'cuda' extra in pyproject.toml
#   -DirectML -> onnxruntime-directml (AMD/Intel, incl. Intel XPU on Windows),
#                equivalent to the 'directml' extra. The two conflict -
#                pick one.
# NOTE: `uv tool install` has no --extra flag (uv 0.9.x), so the runtime
# packages are added with --with. The pins are read from
# [project.optional-dependencies] in pyproject.toml - single source of truth,
# the script cannot drift from the extras.

param(
    [switch]$DirectML
)
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
try {
    Write-Host "Installing pdf4llm via `uv tool install` ..."
    # drop only pdf4llm's cached build artifacts, so a version bump is picked
    # up (uv otherwise reuses the cached wheel); nvidia wheels stay cached
    uv cache clean pdf4llm | Out-Null

    # Read the GPU runtime pins from pyproject.toml (tomllib needs Python
    # >= 3.11, which uv provides/manages; --no-project keeps it out of
    # the dev environment). Single quotes inside: PowerShell strips
    # double quotes when passing args to native executables.
    $extrasJson = (& uv run --no-project python -c @'
import json, tomllib
print(json.dumps(tomllib.load(open('pyproject.toml', 'rb'))['project']['optional-dependencies']))
'@) -split "`r?`n" | Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if (-not $extrasJson) {
        throw "Could not read [project.optional-dependencies] from pyproject.toml"
    }
    $deps = $extrasJson | ConvertFrom-Json
    $extraName = if ($DirectML) { "directml" } else { "cuda" }
    $gpuArgs = @()
    foreach ($dep in $deps.$extraName) {
        $gpuArgs += @("--with", $dep)
    }
    Write-Host "  GPU runtime ($extraName): $($gpuArgs -join ' ')"
    uv tool install --force . @gpuArgs
    if ($LASTEXITCODE -ne 0) {
        throw "uv tool install failed"
    }

    # pymupdf pulls the CPU-only onnxruntime transitively, so both wheels land
    # in the tool env and share the onnxruntime/ package dir - whichever was
    # installed last wins its files. Re-apply the GPU wheel on top so the CUDA
    # EP is always the active one (no-op when up to date, cached):
    if (-not $DirectML) {
        $venvPython = Join-Path (& uv tool dir) "pdf4llm/Scripts/python.exe"
        & uv pip install --python $venvPython --reinstall-package onnxruntime-gpu onnxruntime-gpu | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "onnxruntime-gpu re-apply failed"
        }
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
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
    }
    if (Test-Path $shim) {
        Copy-Item -Path $shim -Destination (Join-Path $dest "pdf4llm.exe") -Force
        Write-Host "Installed pdf4llm.exe to $dest"
    }
}
finally {
    Pop-Location
}
