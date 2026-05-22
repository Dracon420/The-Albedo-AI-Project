# resume_after_quota.ps1 — Run this AFTER your GPU quota increase is approved.
# The workspace (albedo-ml) is already created. This script:
#   1. Creates the T4 GPU compute cluster
#   2. Uploads the training dataset
#   3. Submits the fine-tune job
#   4. Streams logs until complete

$ErrorActionPreference = "Stop"
$az         = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
$SUB_ID     = "b6737d60-b1c5-4178-8fed-0b940685b3e"
$RG         = "albedo-training-rg"
$WORKSPACE  = "albedo-ml"
$COMPUTE    = "albedo-gpu"
$DATASET    = "albedo-dataset"
$DATA_FILE  = "..\training_data\albedo_dataset.jsonl"

& $az account set --subscription $SUB_ID

# ── Step 1: Compute cluster ───────────────────────────────────────────────────
Write-Host "`n[1/3] Creating GPU compute cluster (T4 16GB, spot)..." -ForegroundColor Cyan
& $az ml compute create `
    --name $COMPUTE `
    --type AmlCompute `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --size Standard_NC4as_T4_v3 `
    --min-instances 0 `
    --max-instances 1 `
    --tier low_priority `
    --output table

# ── Step 2: Upload dataset ────────────────────────────────────────────────────
Write-Host "`n[2/3] Uploading training dataset..." -ForegroundColor Cyan
& $az ml data create `
    --name $DATASET `
    --version 1 `
    --path $DATA_FILE `
    --type uri_file `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --output table

# ── Step 3: Submit training job ───────────────────────────────────────────────
Write-Host "`n[3/3] Submitting fine-tune job..." -ForegroundColor Cyan
$JOB_JSON = & $az ml job create `
    --file job.yml `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --output json

$JOB_NAME = ($JOB_JSON | ConvertFrom-Json).name
Write-Host "`n✓ Job submitted: $JOB_NAME" -ForegroundColor Green

# Save for download.ps1
$JOB_NAME | Out-File -FilePath "last_job_name.txt" -Encoding utf8

Write-Host ""
Write-Host "Monitor at:" -ForegroundColor Yellow
Write-Host "  https://ml.azure.com/runs/$JOB_NAME?wsid=/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.MachineLearningServices/workspaces/$WORKSPACE"
Write-Host ""
Write-Host "Streaming logs (Ctrl+C to detach, job keeps running)..." -ForegroundColor Cyan
& $az ml job stream --name $JOB_NAME --resource-group $RG --workspace-name $WORKSPACE

Write-Host "`nWhen complete, run download.ps1 to pull the GGUF and register albedo-3b." -ForegroundColor Cyan
