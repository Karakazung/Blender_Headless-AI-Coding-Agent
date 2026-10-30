<#
.SYNOPSIS
    Blender Path Resolution Protocol (6-Tier Cascade)
    Resolves the blender.exe path dynamically without hardcoding.
#>

param(
    [string]$CacheFile = "blender_path.txt"
)

# 1. Workspace Cache
if (Test-Path $CacheFile) {
    $cached = (Get-Content $CacheFile -Raw -ErrorAction SilentlyContinue).Trim()
    if ($cached -and (Test-Path $cached)) {
        Write-Output "BLENDER_PATH=$cached"
        exit 0
    }
}

# 2. Environment Variable
if ($env:BLENDER_PATH -and (Test-Path $env:BLENDER_PATH)) {
    $env:BLENDER_PATH | Out-File -FilePath $CacheFile -Encoding utf8
    Write-Output "BLENDER_PATH=$env:BLENDER_PATH"
    exit 0
}

# 3. System PATH
$fromPath = (Get-Command blender.exe -ErrorAction SilentlyContinue).Source
if ($fromPath -and (Test-Path $fromPath)) {
    $fromPath | Out-File -FilePath $CacheFile -Encoding utf8
    Write-Output "BLENDER_PATH=$fromPath"
    exit 0
}

# 4. Registry Uninstall Keys
$regKeys = @(
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
)

foreach ($rk in $regKeys) {
    $installed = Get-ItemProperty $rk -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like "*Blender*" -and $_.InstallLocation }
    foreach ($item in $installed) {
        $exe = Join-Path $item.InstallLocation "blender.exe"
        if (Test-Path $exe) {
            $exe | Out-File -FilePath $CacheFile -Encoding utf8
            Write-Output "BLENDER_PATH=$exe"
            exit 0
        }
    }
}

# 5. Common Installation Directories
$commonGlobs = @(
    "C:\Program Files\Blender Foundation\Blender *\blender.exe",
    "C:\Program Files\Steam\steamapps\common\Blender\blender.exe",
    "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
    "D:\Games\Steam\steamapps\common\Blender\blender.exe",
    "D:\SteamLibrary\steamapps\common\Blender\blender.exe",
    "D:\Steam\steamapps\common\Blender\blender.exe",
    "D:\Blender*\blender.exe",
    "$env:LOCALAPPDATA\Programs\Blender Foundation\Blender *\blender.exe"
)

foreach ($pattern in $commonGlobs) {
    $resolved = Resolve-Path $pattern -ErrorAction SilentlyContinue
    if ($resolved) {
        $first = $resolved[0].Path
        $first | Out-File -FilePath $CacheFile -Encoding utf8
        Write-Output "BLENDER_PATH=$first"
        exit 0
    }
}

# 6. Fallback Exit 1
Write-Error "BLENDER_NOT_FOUND: All 6 cascade levels failed. Please specify blender.exe path manually in $CacheFile."
exit 1

