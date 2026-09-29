<#
showtime end-to-end test on Windows 10/11 desktop, run as a standard (non-administrator) user.

From a clone of the repository, in a normal (not "Run as administrator") PowerShell window:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\e2e-windows.ps1

Needs uv and Node.js 22 or 24 (README "Requirements"); no Python install is needed (uv provides one).
It records the machine, checks the Windows entry points (showtime.cmd; showtime.ps1 under this machine's
execution policy; a UTF-8-with-BOM script as Windows PowerShell 5.1 writes it), then runs scripts\e2e.py:
a fresh `showtime setup` (default tier), doctor, a short voiced render with qa, HTML export, transcription,
captions, the MCP server handshake and the fast test suite. Setup downloads about 3 GB the first time.
Results go to "%USERPROFILE%\showtime e2e" (a path with a space on purpose) and showtime-e2e.zip next to
it: summary.md, logs\, the render and the HTML export. Exit code 0 when everything passed.

    -SkipSetup    use the runtime already in %USERPROFILE%\.showtime
    -NoSuite      skip the fast test suite (it takes 20-40 minutes on a 4-core laptop)
    -AllowAdmin   run elevated anyway (CI runners are administrators)
#>
param(
    [string]$Out = (Join-Path $env:USERPROFILE 'showtime e2e'),
    [switch]$SkipSetup,
    [switch]$NoSuite,
    [string]$SuiteArgs = '-j auto',
    [switch]$AllowAdmin
)
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $repo 'skills\showtime\bin'
New-Item -ItemType Directory -Force -Path (Join-Path $Out 'logs') | Out-Null
$facts = Join-Path $Out 'windows-facts.txt'

# 1. the machine
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
$uv = Get-Command uv -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
$node = Get-Command node -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
$lines = @(
    "os: $($os.Caption) $($os.Version) build $($os.BuildNumber) ($($os.OSArchitecture))",
    "edition: $((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction SilentlyContinue).EditionID)",
    "cpu: $($cpu.Name) ($($cpu.NumberOfLogicalProcessors) threads); PROCESSOR_ARCHITECTURE=$env:PROCESSOR_ARCHITECTURE",
    "ram GB: $([math]::Round($os.TotalVisibleMemorySize / 1MB, 1))",
    "user: $(whoami)  elevated: $elevated",
    "execution policy: $(Get-ExecutionPolicy)  ($((Get-ExecutionPolicy -List | ForEach-Object { "$($_.Scope)=$($_.ExecutionPolicy)" }) -join ', '))",
    "powershell: $($PSVersionTable.PSVersion) $($PSVersionTable.PSEdition)",
    "uv: $uv $(if ($uv) { & $uv --version })",
    "node: $node $(if ($node) { & $node --version })",
    "repo: $repo",
    "out: $Out"
)
function Note([string[]]$text) { $text | ForEach-Object { Write-Host $_ }; Add-Content -Path $facts -Value $text -Encoding utf8 }
Set-Content -Path $facts -Value '' -Encoding utf8
Note $lines
if ($elevated -and -not $AllowAdmin) {
    Write-Host "This test is for a standard user: open a normal PowerShell window (not 'Run as administrator'), or pass -AllowAdmin."
    exit 2
}
if (-not $uv -or -not $node) {
    Write-Host "Install the prerequisites first (README 'Requirements'), then open a new PowerShell window:"
    Write-Host "  winget install --id=astral-sh.uv -e"
    Write-Host "  winget install OpenJS.NodeJS.LTS --source winget"
    exit 2
}

# 2. Windows entry points
$winSteps = @()
function Step([string]$name, [scriptblock]$block, [string]$expectText = '') {
    $log = Join-Path $Out "logs\windows-$name.txt"
    $t = Get-Date
    $text = (& $block 2>&1 | Out-String -Width 300)
    $rc = $LASTEXITCODE
    Set-Content -Path $log -Value $text -Encoding utf8
    # an exception printed by an exit hook leaves the exit code at 0: a traceback fails the step too
    $ok = ($rc -eq 0) -and ((-not $expectText) -or $text.Contains($expectText)) -and
          (-not $text.Contains('Traceback (most recent call last)'))
    $sec = [math]::Round(((Get-Date) - $t).TotalSeconds, 1)
    $script:winSteps += [pscustomobject]@{ step = $name; ok = $ok; rc = $rc; seconds = $sec }
    "{0,-5} {1,-22} rc={2,-3} {3,6}s" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name, $rc, $sec
}
Step 'cmd-shim' { & (Join-Path $bin 'showtime.cmd') --version } 'showtime'
# showtime.ps1 runs only where the execution policy allows scripts (Windows 10/11 desktop default: Restricted).
$ps1 = Join-Path $bin 'showtime.ps1'
$log = Join-Path $Out 'logs\windows-ps1-shim.txt'
# without the -ExecutionPolicy this script was started with (a child inherits it through the environment)
$inherited = $env:PSExecutionPolicyPreference
Remove-Item Env:PSExecutionPolicyPreference -ErrorAction SilentlyContinue
$text = (powershell -NoProfile -Command "& '$ps1' version" 2>&1 | Out-String -Width 300)
$ps1Rc = $LASTEXITCODE
if ($inherited) { $env:PSExecutionPolicyPreference = $inherited }
Set-Content -Path $log -Value $text -Encoding utf8
$ps1Result = if ($ps1Rc -eq 0) { 'runs' } elseif ($text -match 'running scripts is disabled|cannot be loaded') { 'blocked by the execution policy; showtime.cmd is the entry point' } else { "failed (rc $ps1Rc)" }
Note "info  ps1-shim               $ps1Result"

# 3. the end-to-end run (scripts\e2e.py through uv's Python; the showtime calls go through showtime.cmd)
$e2eArgs = @('run', '--no-project', '--python', '3.12', 'python', (Join-Path $repo 'scripts\e2e.py'), '--out', $Out,
             '--suite-args', $SuiteArgs)
if ($SkipSetup) { $e2eArgs += '--skip-setup' }
if ($NoSuite) { $e2eArgs += '--no-suite' }
& $uv @e2eArgs
$e2eRc = $LASTEXITCODE

# 4. a narration file written the way Windows PowerShell 5.1 writes UTF-8 (with a byte-order mark)
$job = Get-ChildItem (Join-Path $Out 'work\showtime-out') -Directory -Filter 'e2e-*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName
if ($job) {
    $bom = Join-Path $job 'narration-bom.md'
    $cafe = 'Caf' + [char]0xE9   # this file stays ASCII: Windows PowerShell 5.1 reads BOM-less scripts as ANSI
    [IO.File]::WriteAllText($bom, "## hero`r`n$cafe-quality narration, written with a byte-order mark.`r`n", (New-Object Text.UTF8Encoding $true))
    Step 'bom-narration' { & (Join-Path $bin 'showtime.cmd') voice script $bom -o (Join-Path $job 'voice-bom') } 'timeline.json'
}

# 5. results
$ok = ($e2eRc -eq 0) -and -not ($winSteps | Where-Object { -not $_.ok })
Note ($winSteps | Format-Table -AutoSize | Out-String)
$zip = Join-Path (Split-Path -Parent $Out) 'showtime-e2e.zip'
$pack = @(@((Join-Path $Out 'summary.md'), (Join-Path $Out 'summary.json'), $facts, (Join-Path $Out 'logs')) |
    Where-Object { Test-Path $_ })
if ($job) {
    $pack += @(@('final.mp4', 'final.captioned.mp4', 'subs.srt', 'exports') | ForEach-Object { Join-Path $job $_ } |
        Where-Object { Test-Path $_ })
}
Compress-Archive -Force -Path $pack -DestinationPath $zip
Write-Host ""
Write-Host $(if ($ok) { "ALL PASSED" } else { "SOMETHING FAILED: see $Out\summary.md and $Out\logs" })
Write-Host "results: $zip"
if ($ok) { exit 0 } else { exit 1 }
