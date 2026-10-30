<#
.SYNOPSIS
    Run Blender in Headless Mode with Automated Preflight & Output Isolation.
#>

param(
    [string]$Script = "",
    [string]$PythonExpr = "",
    [switch]$Probe = $false,
    [string]$OutDir = "out"
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$cacheFile = Join-Path $rootDir "blender_path.txt"

# Resolve Blender Path
$findScript = Join-Path $scriptDir "find_blender.ps1"
$blenderPathOutput = powershell -NoProfile -File $findScript -CacheFile $cacheFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "Could not resolve Blender path. Please update $cacheFile manually."
    exit 1
}

$blenderExe = ($blenderPathOutput -split "=")[1].Trim()
Write-Host "[+] Using Blender executable: $blenderExe"

# Ensure output directory exists
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

# 1. Probe Mode
if ($Probe) {
    Write-Host "[*] Executing Preflight Probe..."
    & $blenderExe --background --python-expr "import bpy; print('>>> BLENDER_VERSION:', bpy.app.version_string); print('>>> PYTHON_VERSION:', bpy.app.build_commit_date)"
    exit $LASTEXITCODE
}

# 2. Python Expression Mode
if ($PythonExpr) {
    Write-Host "[*] Executing Python Expression in Headless Mode..."
    & $blenderExe --background --python-expr $PythonExpr
    exit $LASTEXITCODE
}

# 3. Script Execution Mode
if ($Script) {
    if (-not (Test-Path $Script)) {
        Write-Error "Script file not found: $Script"
        exit 1
    }
    Write-Host "[*] Executing Headless Script: $Script"
    & $blenderExe --background --python $Script -- --out-dir $OutDir
    exit $LASTEXITCODE
}

Write-Host "Usage:"
Write-Host "  .\\run_headless.ps1 -Probe"
Write-Host "  .\\run_headless.ps1 -Script scripts\\template_worker.py"
Write-Host "  .\\run_headless.ps1 -PythonExpr `"import bpy; print(bpy.data.objects.keys())`""
