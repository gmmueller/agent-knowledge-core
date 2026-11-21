# Install qmd (local markdown search: github.com/tobi/qmd) globally and make it run under Bun on Windows.
#
# Why: on Windows, qmd under Node crashes with an access violation (exit -1073741819) as soon as it loads the
# sqlite-vec extension into better-sqlite3. Bun runs it fine. npm's global shims always launch Node, so this
# script rewrites the three shims (qmd, qmd.cmd, qmd.ps1) to launch Bun instead.
# Re-run after every `npm install -g @tobilu/qmd` (an upgrade restores the Node shims).
#
# Usage: powershell -ExecutionPolicy Bypass -File tools\install_qmd.ps1 -Brain <brain> [-SkipInstall]
# Example: .\tools\install_qmd.ps1 -Brain <workspace>\my-course -SkipInstall -Collections wiki,raw
param([Parameter(Mandatory=$true)][string]$Brain, [switch]$SkipInstall, [string[]]$Collections = @())
$ErrorActionPreference = 'Stop'
$brainPath = (Resolve-Path -LiteralPath $Brain).Path
if (-not (Test-Path -LiteralPath (Join-Path $brainPath 'brain.md'))) { throw 'Brain must contain brain.md.' }
foreach ($collection in $Collections) {
    if ($collection -notin @('wiki', 'raw')) { throw 'Collections must be wiki or raw.' }
}

if (-not (Get-Command bun -ErrorAction SilentlyContinue)) { throw 'Bun is required (https://bun.sh); install it first.' }
if (-not $SkipInstall) { npm install -g '@tobilu/qmd' | Out-Host }

$npmDir = (npm prefix -g).Trim()
$entry  = Join-Path $npmDir 'node_modules\@tobilu\qmd\dist\cli\qmd.js'
if (-not (Test-Path $entry)) { throw "qmd entry not found: $entry" }

$utf8 = New-Object Text.UTF8Encoding $false
[IO.File]::WriteAllText((Join-Path $npmDir 'qmd.cmd'),
  "@ECHO off`r`nREM Patched by agent-knowledge-core tools\install_qmd.ps1: run qmd under Bun (Node crashes loading sqlite-vec on Windows)`r`nbun `"%~dp0node_modules\@tobilu\qmd\dist\cli\qmd.js`" %*`r`n", $utf8)
[IO.File]::WriteAllText((Join-Path $npmDir 'qmd.ps1'),
  "# Patched by agent-knowledge-core tools\install_qmd.ps1: run qmd under Bun`r`n& bun `"`$PSScriptRoot\node_modules\@tobilu\qmd\dist\cli\qmd.js`" @args`r`nexit `$LASTEXITCODE`r`n", $utf8)
[IO.File]::WriteAllText((Join-Path $npmDir 'qmd'),
  "#!/bin/sh`n# Patched by agent-knowledge-core tools/install_qmd.ps1: run qmd under Bun`nbasedir=`$(dirname `"`$(echo `"`$0`" | sed -e 's,\\\\,/,g')`")`nexec bun `"`$basedir/node_modules/@tobilu/qmd/dist/cli/qmd.js`" `"`$@`"`n", $utf8)

& qmd --version
Write-Host "qmd shims in $npmDir now run under Bun."

foreach ($collection in $Collections) {
    & qmd collection add (Join-Path $brainPath $collection) --name "$(Split-Path $brainPath -Leaf)-$collection"
    if ($LASTEXITCODE -ne 0) { throw "Could not add $collection collection." }
}
