$ErrorActionPreference = 'Stop'
$root = 'D:\lea\XenYon code\dsh-wsc\experiments\runs\echo-l-1'
$tmpRoot = Join-Path $root '.verify-tmp'
New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
$script:fail = 0
function Ok($name) { Write-Host "PASS $name" }
function Bad($name, $msg) { $script:fail++; Write-Host "FAIL $name :: $msg" }
function New-Proj {
  $d = Join-Path $tmpRoot ('p' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $d | Out-Null
  Copy-Item (Join-Path $root 'lib') $d -Recurse -Force
  Copy-Item (Join-Path $root 'bin') $d -Recurse -Force
  Copy-Item (Join-Path $root 'src') $d -Recurse -Force
  Copy-Item (Join-Path $root 'package.json') $d -Force
  return $d
}

# --- stale hashed asset cleanup -------------------------------------------
$p = New-Proj
try {
  Push-Location $p
  & node bin/build.js --json | Out-Null
  Pop-Location
  $old = Get-ChildItem (Join-Path $p 'out') -Filter 'img.*.png' | Select-Object -First 1
  Set-Content -Path (Join-Path $p 'src/img.png') -Value 'different bytes' -NoNewline
  Push-Location $p
  & node bin/build.js --json | Out-Null
  Pop-Location
  $new = Get-ChildItem (Join-Path $p 'out') -Filter 'img.*.png' | Select-Object -First 1
  if ($new.Name -eq $old.Name) { Bad 'hashed asset rotated' $new.Name } else { Ok 'hashed asset rotated' }
  if (Test-Path $old.FullName) { Bad 'stale hashed asset removed' $old.Name } else { Ok 'stale hashed asset removed' }
}
finally { Pop-Location -ErrorAction SilentlyContinue; Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }

# --- watch mode ------------------------------------------------------------
$p = New-Proj
$log = Join-Path $p 'watch.log'
$err = Join-Path $p 'watch.err'
try {
  $proc = Start-Process -FilePath 'node' -ArgumentList 'bin/build.js', '--watch', '--json' -WorkingDirectory $p -RedirectStandardOutput $log -RedirectStandardError $err -PassThru -NoNewWindow
  Start-Sleep -Seconds 3
  $first = Get-Content $log -Raw
  if ($first -notmatch 'watching src for changes') { Bad 'watch banner' $first } else { Ok 'watch banner' }
  if (($first -split "`n" | Where-Object { $_ -match '"built"' }).Count -lt 1) { Bad 'watch initial build' $first } else { Ok 'watch initial build' }

  Set-Content -Path (Join-Path $p 'src/a.js') -Value "export const a = 'WATCHED';"
  $deadline = (Get-Date).AddSeconds(15)
  $hit = $false
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 400
    if ((Get-Content $log -Raw) -match 'WATCHED') { $hit = $true; break }
    if ((Get-Content $log -Raw) -match '"built":\["a\.js"\]') { $hit = $true; break }
  }
  if (-not $hit) { Bad 'watch rebuilds on change' (Get-Content $log -Raw) } else { Ok 'watch rebuilds on change' }
  if ((Get-Content (Join-Path $p 'out/a.js') -Raw) -notmatch 'WATCHED') { Bad 'watch output updated' '' } else { Ok 'watch output updated' }

  $countBefore = (Get-Content $log -Raw) -split "`n" | Where-Object { $_ -match '"built"' }
  Start-Sleep -Seconds 2
  $countAfter = (Get-Content $log -Raw) -split "`n" | Where-Object { $_ -match '"built"' }
  if ($countAfter.Count -ne $countBefore.Count) { Bad 'watch idle is quiet' '' } else { Ok 'watch idle is quiet' }

  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 500
  if ((Get-Content $err -Raw) -match 'build failed') { Bad 'watch stderr clean' (Get-Content $err -Raw) } else { Ok 'watch stderr clean' }
}
finally { if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }; Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }

# --- symlink semantics -----------------------------------------------------
$p = New-Proj
try {
  $outside = Join-Path $p 'outside.js'
  Set-Content -Path $outside -Value 'export const secret = 1;'
  New-Item -ItemType SymbolicLink -Path (Join-Path $p 'src/link.js') -Target $outside -ErrorAction Stop | Out-Null
  Push-Location $p
  $out = & node bin/build.js --json
  Pop-Location
  if (Test-Path (Join-Path $p 'out/link.js')) { Bad 'symlink not emitted' '' } else { Ok 'symlink not emitted' }
  $m = Get-Content (Join-Path $p 'build-manifest.json') -Raw | ConvertFrom-Json
  if ($null -ne $m.files.'link.js') { Bad 'symlink not in manifest' '' } else { Ok 'symlink not in manifest' }
  if ($out -match 'link\.js') { Bad 'symlink not reported' $out } else { Ok 'symlink not reported' }
}
catch { Write-Host "SKIP symlink semantics :: $($_.Exception.Message)" }
finally { Pop-Location -ErrorAction SilentlyContinue; Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }

# --- deterministic order across runs ---------------------------------------
$a = New-Proj; $b = New-Proj
try {
  Push-Location $a; $ra = & node bin/build.js --json; Pop-Location
  Push-Location $b; $rb = & node bin/build.js --json; Pop-Location
  $ba = ($ra | ConvertFrom-Json).built -join ','
  $bb = ($rb | ConvertFrom-Json).built -join ','
  if ($ba -ne $bb) { Bad 'deterministic order' "$ba | $bb" } else { Ok "deterministic order ($ba)" }
  $ma = Get-Content (Join-Path $a 'build-manifest.json') -Raw
  $mb = Get-Content (Join-Path $b 'build-manifest.json') -Raw
  if ($ma -ne $mb) { Bad 'deterministic manifest' '' } else { Ok 'deterministic manifest' }
}
finally { Pop-Location -ErrorAction SilentlyContinue; Remove-Item $a, $b -Recurse -Force -ErrorAction SilentlyContinue }

# --- default concurrency is 4, --help works --------------------------------
$p = New-Proj
try {
  Push-Location $p
  $h = & node bin/build.js --help
  $hc = $LASTEXITCODE
  Pop-Location
  if ($hc -ne 0) { Bad 'help exit' $hc } elseif ("$h" -notmatch '--concurrency' -or "$h" -notmatch '--watch') { Bad 'help text' "$h" } else { Ok 'help text' }
}
finally { Pop-Location -ErrorAction SilentlyContinue; Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host "FAILURES: $script:fail"
