# showtime: PowerShell entry point. Finds Python and runs lib/st/launcher.py.
# Override the interpreter with $env:SHOWTIME_PYTHON.
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot '..\lib\st\launcher.py'
$stHome = if ($env:SHOWTIME_HOME) { $env:SHOWTIME_HOME } else { Join-Path $HOME '.showtime' }

function Test-Python([string]$exe, [string[]]$pre) {
    try {
        & $exe @pre -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

if ($env:SHOWTIME_PYTHON) {
    & $env:SHOWTIME_PYTHON $launcher @args; exit $LASTEXITCODE
}
$venvPy = Join-Path $stHome 'venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { $venvPy = Join-Path $stHome 'venv/bin/python' }
# setup may rebuild the venv, and Windows cannot delete a running python.exe: run it with a Python outside the venv
$isSetup = ($args.Count -gt 0 -and "$($args[0])" -eq 'setup')
if ((Test-Path $venvPy) -and -not $isSetup) {
    & $venvPy $launcher @args; exit $LASTEXITCODE
}
if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-Python 'py' @('-3'))) {
    & py -3 $launcher @args; exit $LASTEXITCODE
}
foreach ($name in @('python3', 'python')) {
    if ((Get-Command $name -ErrorAction SilentlyContinue) -and (Test-Python $name @())) {
        & $name $launcher @args; exit $LASTEXITCODE
    }
}
$uv = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $uv) {
    # a fresh uv install is not on this app's PATH until it restarts: try the installers' folders
    $uvHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
    $cands = @((Join-Path $uvHome '.local\bin\uv.exe'), (Join-Path $uvHome '.cargo\bin\uv.exe'),
               (Join-Path $HOME '.local/bin/uv'), (Join-Path $HOME '.cargo/bin/uv'))
    if ($env:LOCALAPPDATA) { $cands += (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe') }
    $uv = $cands | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
}
if ($uv) {
    & $uv run --no-project --python 3.12 python $launcher @args; exit $LASTEXITCODE
}
if (Test-Path $venvPy) {
    & $venvPy $launcher @args; exit $LASTEXITCODE
}
Write-Error ("showtime: no Python 3.8+ found. Install uv: " +
  'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"' +
  " (or Python 3 from https://www.python.org/downloads/), then run: showtime setup. " +
  "If you just installed one, restart your coding agent (or open a new terminal) so it sees the new PATH.")
exit 127
