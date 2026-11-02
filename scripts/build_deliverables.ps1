# Generate sample results, run the evaluation and build the report. Stops at the first failure.
# Run again after a coaching session to include it.
param([switch]$ReportOnly)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = '.\.venv\Scripts\python.exe'

function Step($name, [string[]]$arguments) {
    Write-Host "== $name"
    & $py @arguments
    if ($LASTEXITCODE -ne 0) { throw "$name failed" }
}

if (-not $ReportOnly) {
    Step 'Check API key' @('-m', 'coworkers', 'check')
    Step 'Replay past briefs' @('-m', 'coworkers', 'replay', '--days', '5')
    Step 'Live brief' @('-m', 'coworkers', 'daily')
}
Step 'Evaluation' @('-X', 'utf8', 'eval\run_eval.py')
Step 'Diagrams' @('scripts\make_diagrams.py')
Step 'Report' @('scripts\build_report.py')
Step 'Status' @('-m', 'coworkers', 'status')
