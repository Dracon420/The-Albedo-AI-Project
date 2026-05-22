# setup_and_run.ps1 — Albedo Azure ML training setup
# Run this from: C:\Users\demon\Desktop\Local Cortana AI\azure_training\
# Requires: az login already completed, az ml extension installed

$ErrorActionPreference = "Stop"
$SUB_ID    = "b6737d60-b1c5-4178-8fed-0b940685b3e"
$RG        = "albedo-training-rg"
$LOCATION  = "eastus"
$WORKSPACE = "albedo-ml"
$COMPUTE   = "albedo-gpu"
$DATASET   = "albedo-dataset"
$DATA_FILE = "..\training_data\albedo_dataset.jsonl"

Write-Host "`n[1/7] Setting subscription..." -ForegroundColor Cyan
az account set --subscription $SUB_ID

Write-Host "`n[2/7] Installing Azure ML CLI extension (if needed)..." -ForegroundColor Cyan
az extension add --name ml --upgrade --yes 2>$null

Write-Host "`n[3/7] Creating resource group: $RG in $LOCATION..." -ForegroundColor Cyan
az group create --name $RG --location $LOCATION --output table

Write-Host "`n[4/7] Creating Azure ML workspace: $WORKSPACE (takes ~2 min)..." -ForegroundColor Cyan
az ml workspace create `
    --name $WORKSPACE `
    --resource-group $RG `
    --location $LOCATION `
    --output table

Write-Host "`n[5/7] Creating GPU compute cluster: $COMPUTE (T4 16GB, spot pricing)..." -ForegroundColor Cyan
az ml compute create `
    --name $COMPUTE `
    --type AmlCompute `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --size Standard_NC4as_T4_v3 `
    --min-instances 0 `
    --max-instances 1 `
    --tier low_priority `
    --output table

Write-Host "`n[6/7] Uploading training dataset..." -ForegroundColor Cyan
az ml data create `
    --name $DATASET `
    --version 1 `
    --path $DATA_FILE `
    --type uri_file `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --output table

Write-Host "`n[7/7] Submitting training job..." -ForegroundColor Cyan
$JOB_OUTPUT = az ml job create `
    --file job.yml `
    --resource-group $RG `
    --workspace-name $WORKSPACE `
    --output json | ConvertFrom-Json

$JOB_NAME = $JOB_OUTPUT.name
Write-Host "`n✓ Job submitted: $JOB_NAME" -ForegroundColor Green
Write-Host ""
Write-Host "Monitor live at:" -ForegroundColor Yellow
Write-Host "  https://ml.azure.com/runs/$JOB_NAME?wsid=/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.MachineLearningServices/workspaces/$WORKSPACE"
Write-Host ""
Write-Host "Or stream logs with:" -ForegroundColor Yellow
Write-Host "  az ml job stream --name $JOB_NAME --resource-group $RG --workspace-name $WORKSPACE"
Write-Host ""
Write-Host "When complete, run download.ps1 to pull the GGUF file." -ForegroundColor Cyan

# Save job name for download script
$JOB_NAME | Out-File -FilePath "last_job_name.txt" -Encoding utf8
