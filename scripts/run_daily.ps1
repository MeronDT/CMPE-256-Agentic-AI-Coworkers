# Generate today's brief. Schedule this with Windows Task Scheduler to run every morning.
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m coworkers daily *>> data\daily.log
