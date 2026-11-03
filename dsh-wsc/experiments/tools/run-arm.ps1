$ErrorActionPreference = 'Continue'
$tools = $PSScriptRoot
$arm = $args[0]

# Fail before spending an hour: an arm whose package copy predates the source
# runs the old behaviour, which reads as "the flag does nothing".
& node (Join-Path $tools 'verify-arms.mjs') "ab-echo-$arm"
if ($LASTEXITCODE -ne 0) {
  "arm ab-echo-$arm does not match the source; refusing to run"
  exit 1
}

$plan = if ($arm -eq 'a') { @('echo-a-2', 'echo-a-3') } else { @('echo-c-1', 'echo-c-2') }
foreach ($name in $plan) {
  $started = Get-Date
  & pwsh -NoProfile -File (Join-Path $tools 'trial.ps1') -Profile "ab-echo-$arm" -Name $name 2>&1 | Select-Object -Last 2
  "[{0}] {1} finished in {2:N0}s" -f (Get-Date -Format 'HH:mm:ss'), $name, ((Get-Date) - $started).TotalSeconds
}
"=== arm $arm done ==="
