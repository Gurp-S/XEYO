# Run one trial: copy the fixture, run the fixed prompt under one profile,
# score the result, and archive the raw metrics.
#
#   pwsh -File trial.ps1 -Profile ab-a -Name a-1
#
# Outputs: experiments/runs/<Name>/ (working tree), experiments/report/raw/<Name>.json
param(
  [Parameter(Mandatory = $true)][string]$Profile,
  [Parameter(Mandatory = $true)][string]$Name,
  [string]$PromptFile = "$PSScriptRoot\..\PROMPT.md",
  [string]$Fixture = 'fixture',
  [string]$HiddenTest = 'hidden\build.test.mjs'
)

$ErrorActionPreference = 'Stop'
$exp = Resolve-Path "$PSScriptRoot\.."
$runs = Join-Path $exp 'runs'
$raw = Join-Path $exp 'report\raw'
New-Item -ItemType Directory -Force -Path $runs, $raw | Out-Null

$runDir = Join-Path $runs $Name
if (Test-Path $runDir) { Remove-Item $runDir -Recurse -Force }
Copy-Item (Join-Path $exp $Fixture) $runDir -Recurse

# A session is keyed by the working directory. A rerun of the same name must not
# resume the previous (possibly aborted) session, or headless hangs and exits
# without output.
$sessionBase = Join-Path $env:USERPROFILE '.dsh\sessions'
Get-ChildItem $sessionBase -Directory -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "*runs-$Name--*" } |
  ForEach-Object { Remove-Item $_.FullName -Recurse -Force }

$prompt = Get-Content $PromptFile -Raw
$log = Join-Path $raw "$Name.log"
$started = Get-Date
Push-Location $runDir
try {
  $out = & dsh --profile $Profile $prompt 2>&1
  $code = $LASTEXITCODE
} finally {
  Pop-Location
}
$seconds = [int]((Get-Date) - $started).TotalSeconds
$out | Set-Content $log -Encoding utf8

$scoreJson = & node (Join-Path $exp 'score.mjs') $runDir (Join-Path $exp $HiddenTest) 2>&1 | Out-String
$scoreJson | Set-Content (Join-Path $raw "$Name.score.json") -Encoding utf8
$score = $scoreJson | ConvertFrom-Json

# The session directory is keyed by the working directory, whose name encodes
# the run path; pick the newest session touched after this run started.
# The working directory name encodes the run name, so the session directory is
# selected by that name. Picking the newest session touched after start instead
# cross-attributes runs that execute concurrently.
$sessionBase = Join-Path $env:USERPROFILE '.dsh\sessions'
$session = Get-ChildItem $sessionBase -Directory |
  Where-Object { $_.Name -like "*-runs-$Name--" } |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
$metrics = $null
$steps = $null
if ($null -ne $session) {
  $file = Get-ChildItem $session.FullName -Filter 'session.jsonl.zstd' -Recurse |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($null -ne $file) {
    $reader = Join-Path $exp 'tools\read-session.mjs'
    $metrics = (& node $reader $file.FullName usage) | ConvertFrom-Json
    $steps = (& node $reader $file.FullName steps) | ConvertFrom-Json
    & node $reader $file.FullName summary | Set-Content (Join-Path $raw "$Name.types.json") -Encoding utf8
  }
}

$record = [ordered]@{
  name         = $Name
  profile      = $Profile
  started      = $started.ToString('s')
  seconds      = $seconds
  exitCode     = $code
  score        = $score.score
  passed       = $score.passed
  total        = $score.total
  failed       = @($score.tests | Where-Object { -not $_.ok } | ForEach-Object { $_.name })
  session      = if ($null -ne $session) { $session.Name } else { $null }
  requests     = if ($null -ne $metrics) { $metrics.requests } else { $null }
  inputTokens  = if ($null -ne $metrics) { $metrics.input } else { $null }
  outputTokens = if ($null -ne $metrics) { $metrics.output } else { $null }
  events       = if ($null -ne $metrics) { $metrics.events } else { $null }
  steps        = $steps
}
$record | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $raw "$Name.json") -Encoding utf8
"$Name profile=$Profile score=$($score.score) seconds=$seconds exit=$code"
