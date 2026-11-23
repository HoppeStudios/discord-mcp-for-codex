$ErrorActionPreference = 'Stop'
# A parent using PowerShell 7 can export an incompatible module search path.
# This worker only uses built in modules from its own Windows PowerShell host.
$env:PSModulePath = Join-Path $PSHOME 'Modules'
# Windows DPAPI decrypts only for the account which saved the secret.
$vault = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexDiscord\bot-token.dpapi'
if (Test-Path -LiteralPath $vault) {
    $secret = Get-Content -LiteralPath $vault -Raw | ConvertTo-SecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { $env:DISCORD_BOT_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
try {
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
    if ((Get-FileHash -LiteralPath $manifest.node -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.nodeSha256) { throw 'Pinned Node runtime changed. Review before use.' }
    foreach ($entry in $manifest.files) {
        $actual = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $entry.name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $entry.sha256) { throw 'Installed Discord MCP payload changed. Review and reinstall it before use.' }
    }
    & $manifest.node (Join-Path $PSScriptRoot 'discord-mcp.mjs')
    exit $LASTEXITCODE
} finally { Remove-Item Env:\DISCORD_BOT_TOKEN -ErrorAction SilentlyContinue }
