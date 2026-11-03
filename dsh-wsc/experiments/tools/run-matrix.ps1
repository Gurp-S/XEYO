# Run the generalisation matrix: every task under both arms, one trial each,
# with a hard per-run timeout so a non-converging run cannot burn quota forever.
#
#   pwsh -File experiments/tools/run-matrix.ps1
param(
  [int]$TimeoutSeconds = 900,
  [string]$WscProfile = 'ab-echo-k',
  [string]$NativeProfile = 'ab-native',
  [string]$Prefix = 'gen'
)

$ErrorActionPreference = 'Continue'
$exp = Resolve-Path "$PSScriptRoot\.."
$trial = Join-Path $PSScriptRoot 'trial.ps1'

$tasks = @(
  @{ Id = 'bugfix';   Fixture = 'fixture-bugfix';   Prompt = "$exp\PROMPT-bugfix.md";  Hidden = 'hidden\slugify.test.mjs' },
  @{ Id = 'feature';  Fixture = 'fixture-feature';  Prompt = "$exp\PROMPT-feature.md"; Hidden = 'hidden\csv-feature.test.mjs' },
  @{ Id = 'refactor'; Fixture = 'fixture-refactor'; Prompt = "$exp\PROMPT-refactor.md"; Hidden = 'hidden\refactor.test.mjs' },
  @{ Id = 'config';   Fixture = 'fixture-config';   Prompt = "$exp\fixture-config\PROMPT-config.md"; Hidden = 'hidden\migration.test.mjs' }
)
$arms = @(
  @{ Id = 'wsc';    Profile = $WscProfile },
  @{ Id = 'native'; Profile = $NativeProfile }
)

foreach ($task in $tasks) {
  foreach ($arm in $arms) {
    $name = "$Prefix-$($task.Id)-$($arm.Id)"
    $started = Get-Date
    $job = Start-Job -ScriptBlock {
      param($trial, $profile, $name, $prompt, $fixture, $hidden)
      & pwsh -NoProfile -File $trial -Profile $profile -Name $name -PromptFile $prompt -Fixture $fixture -HiddenTest $hidden
    } -ArgumentList $trial, $arm.Profile, $name, $task.Prompt, $task.Fixture, $task.Hidden

    $done = Wait-Job $job -Timeout $TimeoutSeconds
    if (-not $done) {
      Stop-Job $job -ErrorAction SilentlyContinue
      $elapsed = [int]((Get-Date) - $started).TotalSeconds
      "$name TIMEOUT after ${elapsed}s"
      & node "$exp\score.mjs" "$exp\runs\$name" "$exp\$($task.Hidden)" 2>&1 |
        Set-Content "$exp\report\raw\$name.score.json" -Encoding utf8
      continue
    }
    $out = Receive-Job $job
    $out | Select-Object -Last 3
    Remove-Job $job -Force
  }
}
'MATRIX DONE'

