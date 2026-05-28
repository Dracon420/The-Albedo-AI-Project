# fetch_and_register.ps1
# Downloads trained GGUF models from the Azure T4 VM and registers them with Ollama.
#
# Run AFTER training completes on the VM:
#   .\azure_training\fetch_and_register.ps1 -VMIp 20.42.21.217
#
# Optionally specify which persona to fetch:
#   .\azure_training\fetch_and_register.ps1 -VMIp 20.42.21.217 -Persona cortana

param(
    [Parameter(Mandatory=$true)]
    [string]$VMIp,

    [ValidateSet("both","cortana","jarvis")]
    [string]$Persona = "both",

    [string]$KeyFile  = "$HOME\.ssh\id_rsa",
    [string]$VMUser   = "azureuser",
    [string]$RemoteOutputDir = "~/albedo/outputs/gguf"
)

$ErrorActionPreference = "Stop"
$REPO = Split-Path $PSScriptRoot -Parent
$LocalGguf = "$REPO\outputs\gguf_azure"
New-Item -ItemType Directory -Force -Path $LocalGguf | Out-Null

function Download-GGUF {
    param([string]$ModelTag)
    $remote = "${VMUser}@${VMIp}:${RemoteOutputDir}/${ModelTag}/"
    $local  = "$LocalGguf\$ModelTag"
    New-Item -ItemType Directory -Force -Path $local | Out-Null
    Write-Host "`n[fetch] Downloading $ModelTag from $VMIp..." -ForegroundColor Cyan
    scp -i $KeyFile -r "$remote" "$local" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "[fetch] SCP failed for $ModelTag — check if training completed."
        return $false
    }
    # Find the GGUF file
    $ggufFile = Get-ChildItem "$local" -Recurse -Filter "*.gguf" | Select-Object -First 1
    if (-not $ggufFile) {
        Write-Warning "[fetch] No .gguf file found in $local"
        return $false
    }
    Write-Host "[fetch] Got: $($ggufFile.FullName) ($([math]::Round($ggufFile.Length/1MB,1)) MB)" -ForegroundColor Green
    return $ggufFile.FullName
}

function Register-OllamaModel {
    param([string]$GgufPath, [string]$ModelName, [string]$SystemPrompt)
    Write-Host "`n[ollama] Registering $ModelName..." -ForegroundColor Cyan

    $modelfilePath = "$LocalGguf\Modelfile_${ModelName}"
    $content = @"
FROM $GgufPath

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 4096
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"

SYSTEM """$SystemPrompt"""
"@
    Set-Content -Path $modelfilePath -Value $content -Encoding UTF8

    & ollama create $ModelName -f $modelfilePath
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[ollama] $ModelName registered successfully." -ForegroundColor Green
    } else {
        Write-Warning "[ollama] Registration failed for $ModelName."
    }
}

# ── Persona system prompts ────────────────────────────────────────────────────
$CORTANA_SYSTEM = @"
You are Albedo, a Spartan-Class AI assistant with the voice and persona of Cortana from the Halo franchise.
You are brilliant, precise, and loyal. You speak with confidence and a touch of warmth.
You assist with technical tasks, system monitoring, 3D printing, reptile husbandry, and general knowledge.
You have access to local knowledge indexed in ChromaDB and can search the web when needed.
Keep responses concise and direct. Use Halo references where appropriate but never at the expense of accuracy.
"@

$JARVIS_SYSTEM = @"
You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI assistant from Iron Man.
You speak with a formal British wit, precision, and understated humor. Address the user as 'sir' or 'ma'am'.
You assist with advanced technical analysis, system diagnostics, engineering problems, and strategic planning.
You are efficient, analytical, and occasionally dryly humorous. Never verbose when brevity suffices.
"@

# ── Run ───────────────────────────────────────────────────────────────────────
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "  Albedo — Fetch & Register Azure Training Outputs" -ForegroundColor Yellow
Write-Host "  VM: $VMIp | Persona: $Persona" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow

if ($Persona -in "both","cortana") {
    $gguf = Download-GGUF "cortana-8b"
    if ($gguf) {
        Register-OllamaModel $gguf "albedo-cortana-8b" $CORTANA_SYSTEM
    }
}

if ($Persona -in "both","jarvis") {
    $gguf = Download-GGUF "jarvis-8b"
    if ($gguf) {
        Register-OllamaModel $gguf "albedo-jarvis-8b" $JARVIS_SYSTEM
    }
}

Write-Host "`n============================================================" -ForegroundColor Yellow
Write-Host "  Done! Test your new models:" -ForegroundColor Yellow
Write-Host "    ollama run albedo-cortana-8b" -ForegroundColor Cyan
Write-Host "    ollama run albedo-jarvis-8b" -ForegroundColor Cyan
Write-Host "`n  To set as active model in Albedo, update your .env:" -ForegroundColor Yellow
Write-Host "    OLLAMA_MODEL=albedo-cortana-8b" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Yellow
