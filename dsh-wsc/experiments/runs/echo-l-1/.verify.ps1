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
function Build($d, [string[]]$extra = @()) {
  Push-Location $d
  $out = & node bin/build.js --json @extra
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0) { throw "build exited $code : $out" }
  return ($out | ConvertFrom-Json)
}
function ReadManifest($d) { Get-Content (Join-Path $d 'build-manifest.json') -Raw | ConvertFrom-Json }

$p = New-Proj
try {
  $r = Build $p
  $man = ReadManifest $p
  if ($man.version -ne 2) { Bad 'manifest version' $man.version } else { Ok 'manifest v2' }
  if (-not $man.files.'a.js') { Bad 'manifest entry a.js' '' } else { Ok 'manifest entry a.js' }
  $js = Get-Content (Join-Path $p 'out/a.js') -Raw
  if ($js -notmatch 'build [0-9a-f]{8}') { Bad 'js footer' $js } else { Ok 'js footer' }
  $css = Get-Content (Join-Path $p 'out/style.css') -Raw
  if ($css -notmatch 'img\.[0-9a-f]{8}\.png') { Bad 'css rewrite' $css } else { Ok 'css rewrite' }
  if (-not (Test-Path (Join-Path $p 'out/data.json'))) { Bad 'json out' '' } else { Ok 'json out' }

  $before = (ReadManifest $p).files.'style.css'
  Set-Content -Path (Join-Path $p 'src/img.png') -Value 'different bytes' -NoNewline
  $r = Build $p
  if ($r.built -notcontains 'style.css') { Bad 'css rebuild on url change' ($r | ConvertTo-Json -Compress) } else { Ok 'css rebuild on url change' }
  $after = (ReadManifest $p).files.'style.css'
  if ($after.deps.'img.png' -eq $before.deps.'img.png') { Bad 'css dep fingerprint updated' '' } else { Ok 'css dep fingerprint updated' }

  Set-Content -Path (Join-Path $p 'src/base.json') -Value "{`n  `"name`": `"base`",`n  `"level`": 2`n}`n"
  $r = Build $p
  if ($r.built -notcontains 'data.json') { Bad 'json rebuild on base change' ($r | ConvertTo-Json -Compress) } else { Ok 'json rebuild on base change' }
  $data = Get-Content (Join-Path $p 'out/data.json') -Raw | ConvertFrom-Json
  if ($data.level -ne 2 -or $data.name -ne 'demo' -or $null -ne $data.extends) { Bad 'json merge result' (Get-Content (Join-Path $p 'out/data.json') -Raw) } else { Ok 'json merge result' }

  $f = Join-Path $p 'src/b.js'
  $st = (Get-Item $f).LastWriteTimeUtc
  Set-Content -Path $f -Value "export const b = 'B2';"
  (Get-Item $f).LastWriteTimeUtc = $st
  $r = Build $p
  if ($r.built -notcontains 'b.js') { Bad 'mtime-preserving rewrite' ($r | ConvertTo-Json -Compress) } else { Ok 'mtime-preserving rewrite' }
  if ((Get-Content (Join-Path $p 'out/b.js') -Raw) -notmatch 'B2') { Bad 'mtime rewrite output' '' } else { Ok 'mtime rewrite output' }

  Remove-Item (Join-Path $p 'src/b.js')
  $r = Build $p
  if ($r.removed -notcontains 'b.js') { Bad 'removed report' ($r | ConvertTo-Json -Compress) } else { Ok 'removed report' }
  if (Test-Path (Join-Path $p 'out/b.js')) { Bad 'output deleted' '' } else { Ok 'output deleted' }
  if ($null -ne (ReadManifest $p).files.'b.js') { Bad 'manifest entry deleted' '' } else { Ok 'manifest entry deleted' }

  Remove-Item (Join-Path $p 'out/a.js')
  $r = Build $p
  if ($r.built -notcontains 'a.js') { Bad 'missing output heals' ($r | ConvertTo-Json -Compress) } else { Ok 'missing output heals' }

  Set-Content -Path (Join-Path $p 'build-manifest.json') -Value '{"version": 2, "files": {"a.js": ' -NoNewline
  $r = Build $p
  if ($r.built.Count -lt 1) { Bad 'truncated manifest tolerated' '' } else { Ok 'truncated manifest tolerated' }
  if ((ReadManifest $p).version -ne 2) { Bad 'manifest rewritten' '' } else { Ok 'manifest rewritten' }

  $r = Build $p
  if ($r.built.Count -ne 0) { Bad 'second build skips' ($r | ConvertTo-Json -Compress) } else { Ok 'second build skips' }
}
finally { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }

$a = New-Proj; $b = New-Proj
try {
  Build $a @('--concurrency', '1') | Out-Null
  Build $b @('--concurrency', '4') | Out-Null
  $da = Get-ChildItem (Join-Path $a 'out') -File | Sort-Object Name | ForEach-Object { $_.Name + ':' + (Get-FileHash $_.FullName).Hash }
  $db = Get-ChildItem (Join-Path $b 'out') -File | Sort-Object Name | ForEach-Object { $_.Name + ':' + (Get-FileHash $_.FullName).Hash }
  if (($da -join '|') -ne ($db -join '|')) { Bad 'concurrency byte identity' '' } else { Ok 'concurrency byte identity' }
}
finally { Remove-Item $a, $b -Recurse -Force -ErrorAction SilentlyContinue }

$p = New-Proj
try {
  Push-Location $p
  $out = & node bin/build.js --concurrency 0 2>&1
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -eq 0 -or "$out" -notmatch 'positive integer') { Bad 'concurrency validation' "$code $out" } else { Ok 'concurrency validation' }
}
finally { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }

$p = New-Proj
try {
  Push-Location $p
  $out = & node bin/build.js --dry-run --json 2>&1
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0) { Bad 'dry-run exit' "$code $out" }
  elseif (Test-Path (Join-Path $p 'out')) { Bad 'dry-run created out' '' }
  elseif (Test-Path (Join-Path $p 'build-manifest.json')) { Bad 'dry-run created manifest' '' }
  else { Ok 'dry-run writes nothing' }
}
finally { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host "FAILURES: $script:fail"
