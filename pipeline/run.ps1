# Windows equivalent of pipeline/run.sh
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$env:PYTHONPATH = $Root
$env:API_URL = if ($env:API_URL) { $env:API_URL } else { "http://localhost:8000" }
Write-Host "Store Intelligence Detection Pipeline"
python -m pipeline.detect --api-url $env:API_URL
