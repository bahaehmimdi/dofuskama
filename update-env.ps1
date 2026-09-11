# Update values in .env without opening an editor.
# Usage:
#   .\update-env.ps1 -GuildId 1234567890
#   .\update-env.ps1 -DiscordToken "xxxxx.yyyyyy.zzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
#   .\update-env.ps1 -GuildId 1234567890 -DiscordToken "..."

param(
    [string]$GuildId,
    [string]$DiscordToken
)

$envFile = Join-Path $PSScriptRoot ".env"

if (-not (Test-Path $envFile)) {
    Write-Error ".env not found next to this script ($envFile). Copy .env.example to .env first."
    exit 1
}

function Set-EnvValue {
    param([string]$Key, [string]$Value, [string]$Path)

    $content = Get-Content $Path
    $pattern = "^$Key="

    if ($content -match $pattern) {
        $content = $content -replace "$pattern.*", "$Key=$Value"
    } else {
        $content += "$Key=$Value"
    }

    Set-Content -Path $Path -Value $content
}

if (-not $GuildId -and -not $DiscordToken) {
    Write-Host "Usage:"
    Write-Host "  .\update-env.ps1 -GuildId <server id>"
    Write-Host "  .\update-env.ps1 -DiscordToken <token>"
    Write-Host "  .\update-env.ps1 -GuildId <server id> -DiscordToken <token>"
    exit 0
}

if ($GuildId) {
    Set-EnvValue -Key "GUILD_ID" -Value $GuildId -Path $envFile
    Write-Host "== GUILD_ID set to $GuildId =="
}

if ($DiscordToken) {
    Set-EnvValue -Key "DISCORD_TOKEN" -Value $DiscordToken -Path $envFile
    Write-Host "== DISCORD_TOKEN updated =="
}

Write-Host ""
Write-Host "Restart the bot for this to take effect (Ctrl+C, then python bot.py)."
