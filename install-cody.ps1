param(
    [string]$LauncherDir = $env:USERPROFILE,
    [string]$RepoRoot = $PSScriptRoot
)

$launcherDirPath = [System.IO.Path]::GetFullPath($LauncherDir)
$repoRootPath = [System.IO.Path]::GetFullPath($RepoRoot)
$launcherPath = Join-Path $launcherDirPath "cody.cmd"

if (-not (Test-Path -LiteralPath $launcherDirPath)) {
    New-Item -ItemType Directory -Path $launcherDirPath -Force | Out-Null
}

$content = @"
@echo off
setlocal

if defined CODY_REPO (
  set "ROOT=%CODY_REPO%"
) else (
  set "ROOT=$repoRootPath"
)

if not exist "%ROOT%\cody.cmd" (
  echo Cody launcher could not find "%ROOT%\cody.cmd".
  echo Set CODY_REPO to the repo path or reinstall the launcher.
  exit /b 1
)

call "%ROOT%\cody.cmd" %*
exit /b %ERRORLEVEL%
"@

Set-Content -LiteralPath $launcherPath -Value $content -Encoding ascii
Write-Host "Installed launcher at $launcherPath"

$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
$pathEntries = @()
if ($userPath) {
    $pathEntries = $userPath.Split(";") | Where-Object { $_ }
}

if ($pathEntries -notcontains $launcherDirPath) {
    Write-Warning "$launcherDirPath is not in the user PATH. Add it if 'cody' is not found in a new shell."
}
