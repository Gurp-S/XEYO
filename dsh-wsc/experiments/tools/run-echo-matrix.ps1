# Echo-collapse A/C matrix: 3 runs per arm, interleaved so machine/API drift
# spreads across both arms instead of loading onto one of them.
#
#   pwsh -File run-echo-matrix.ps1
#
# A arm: defaults. C arm: payloadPriorEchoDepth 1 (collapse nested echo).

$ErrorActionPreference = 'Continue'
$tools = $PSScriptRoot
$plan = @(
  @{ Profile = 'ab-echo-a'; Name = 'echo-a-1' },
  @{ Profile = 'ab-echo-c'; Name = 'echo-c-1' },
  @{ Profile = 'ab-echo-a'; Name = 'echo-a-2' },
  @{ Profile = 'ab-echo-c'; Name = 'echo-c-2' },
  @{ Profile = 'ab-echo-a'; Name = 'echo-a-3' },
  @{ Profile = 'ab-echo-c'; Name = 'echo-c-3' }
)

foreach ($step in $plan) {
  $started = Get-Date
  & pwsh -NoProfile -File (Join-Path $tools 'trial.ps1') -Profile $step.Profile -Name $step.Name 2>&1 |
    Select-Object -Last 2
  "[{0}] {1} finished in {2:N0}s" -f (Get-Date -Format 'HH:mm:ss'), $step.Name, ((Get-Date) - $started).TotalSeconds
}
'=== echo matrix done ==='
