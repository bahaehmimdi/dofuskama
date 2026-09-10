# dofuskama setup — Windows 11 (PowerShell)
# Run with:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = "python"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    $python = "py"
}

Write-Host "== Using $(& $python --version) =="

& $python -m venv .venv

$activate = ".\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Error "Virtual environment activation script not found at $activate"
    exit 1
}
& $activate

pip install --upgrade pip
pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "== Created .env from .env.example -- edit it now and set DISCORD_TOKEN =="
} else {
    Write-Host "== .env already exists, left untouched =="
}

Write-Host ""
Write-Host "== Setup done =="
Write-Host "1) Edit .env and set DISCORD_TOKEN (and GUILD_ID for instant command sync)."
Write-Host "2) Run the bot:"
Write-Host "   .\.venv\Scripts\Activate.ps1"
Write-Host "   python bot.py"
Write-Host ""
Write-Host "== Cloudflare Worker (privacy/terms pages), optional =="
Write-Host "   cd worker"
Write-Host "   wrangler login"
Write-Host "   wrangler deploy"
