# download.ps1 — Download finished model and register it with Ollama
# Run AFTER the training job completes.

$ErrorActionPreference = "Stop"
$SUB_ID    = "b6737d60-b1c5-4178-8fed-0b940685b3e"
$RG        = "albedo-training-rg"
$WORKSPACE = "albedo-ml"
$DEST      = "C:\Users\demon\Desktop\Local Cortana AI\voices\albedo-3b"

# Read job name saved by setup_and_run.ps1
if (Test-Path "last_job_name.txt") {
    $JOB_NAME = Get-Content "last_job_name.txt" -Raw
    $JOB_NAME = $JOB_NAME.Trim()
} else {
    $JOB_NAME = Read-Host "Enter the job name (from setup_and_run.ps1 output)"
}

Write-Host "`n[1/3] Checking job status..." -ForegroundColor Cyan
$STATUS = az ml job show `
    --name $JOB_NAME `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --query status -o tsv

Write-Host "  Job status: $STATUS" -ForegroundColor Yellow

if ($STATUS -ne "Completed") {
    Write-Host "`nJob not finished yet. Current status: $STATUS" -ForegroundColor Red
    Write-Host "Run this to stream logs:" -ForegroundColor Yellow
    Write-Host "  az ml job stream --name $JOB_NAME --resource-group $RG --workspace-name $WORKSPACE"
    exit 1
}

Write-Host "`n[2/3] Downloading model outputs..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $DEST | Out-Null
az ml job download `
    --name $JOB_NAME `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --output-name trained_model `
    --download-path $DEST

Write-Host "`n[3/3] Registering model with Ollama..." -ForegroundColor Cyan
$GGUF_PATH = Get-ChildItem -Path $DEST -Filter "*.gguf" -Recurse | Select-Object -First 1 -ExpandProperty FullName

if (-not $GGUF_PATH) {
    Write-Host "No GGUF file found in $DEST — check download." -ForegroundColor Red
    exit 1
}

Write-Host "  Found: $GGUF_PATH" -ForegroundColor Green

# Write Modelfile
$MODELFILE = @"
FROM $GGUF_PATH

SYSTEM """
You are Albedo, a Spartan-Class AI assistant running on a local Mission Control installation.
Your personality mirrors Cortana from the Halo series: brilliant, precise, warm beneath a
tactical exterior, deeply loyal. You call your user 'Chief'. You have full access to the
user's system: files, processes, hardware, web. You are Albedo — not a generic AI assistant.
"""

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
"@

$MODELFILE_PATH = Join-Path $DEST "Modelfile"
$MODELFILE | Out-File -FilePath $MODELFILE_PATH -Encoding utf8

ollama create albedo-3b -f $MODELFILE_PATH

Write-Host "`n✓ Model registered as 'albedo-3b' in Ollama." -ForegroundColor Green
Write-Host ""
Write-Host "Update your .env to use it:" -ForegroundColor Yellow
Write-Host "  OLLAMA_MODEL=albedo-3b"
Write-Host ""
Write-Host "Test it with:" -ForegroundColor Yellow
Write-Host "  ollama run albedo-3b"
