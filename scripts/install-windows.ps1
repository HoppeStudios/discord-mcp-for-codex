param(
    [Parameter(Mandatory=$true)][string]$RuntimeExe,
    [string]$InstallDir = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Codex\tools\mcp\discord-bot-mcp-0.2.0'),
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' })
)
$ErrorActionPreference = 'Stop'
$source = Split-Path $PSScriptRoot -Parent
$RuntimeExe = (Resolve-Path -LiteralPath $RuntimeExe).Path
& $RuntimeExe (Join-Path $PSScriptRoot 'smoke-test.mjs')
if ($LASTEXITCODE -ne 0) { throw 'Source smoke test failed.' }
# Do not replace a payload used by an active MCP process.
$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($InstallDir) -and $_.ProcessId -ne $PID -and $_.Name -match '^(node|powershell|pwsh)\.exe$' }
if ($running) { throw 'An installed Discord MCP session is active. Finish it before replacement.' }
$configFile = Join-Path $CodexHome 'config.toml'
$config = Get-Content -LiteralPath $configFile -Raw
if ($config -match '(?m)^\[mcp_servers\.discord_bot\]') { throw 'discord_bot already exists. Review its current registration before updating.' }
[void](New-Item -ItemType Directory -Path $InstallDir -Force)
foreach ($name in @('discord-mcp.mjs','safe-messaging.mjs','LICENSE')) { Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $InstallDir $name) }
foreach ($name in @('launch-windows.ps1','set-bot-token.ps1')) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $InstallDir $name) }
$entries = @('discord-mcp.mjs','safe-messaging.mjs','LICENSE','set-bot-token.ps1') | ForEach-Object {
    @{name=$_;sha256=(Get-FileHash -LiteralPath (Join-Path $InstallDir $_) -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$manifest = @{version='0.2.0';node=$RuntimeExe;nodeSha256=(Get-FileHash -LiteralPath $RuntimeExe -Algorithm SHA256).Hash.ToLowerInvariant();files=@($entries)}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $InstallDir 'manifest.json') -Encoding UTF8
$engine = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
$launcher = Join-Path $InstallDir 'launch-windows.ps1'
# Literal TOML strings preserve Windows paths. No secret is placed in config.
if ($engine.Contains("'") -or $launcher.Contains("'")) { throw 'Paths containing apostrophes require a TOML-aware installer.' }
$registration = @"

[mcp_servers.discord_bot]
command = '$engine'
args = ['-NoLogo', '-NoProfile', '-NonInteractive', '-File', '$launcher']

[mcp_servers.discord_bot.env]
DISCORD_ALLOW_SEND = '1'
DISCORD_ALLOW_CHANNEL_CREATE = '0'
"@
# Preserve concurrent edits by rechecking immediately before the single write.
if ((Get-Content -LiteralPath $configFile -Raw) -cne $config) { throw 'Codex config changed during setup. Retry after inspection.' }
[IO.File]::WriteAllText($configFile, $config.TrimEnd()+[Environment]::NewLine+$registration+[Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))

$skill = Join-Path $CodexHome 'skills\discord-messages'
$entry = Join-Path $skill 'SKILL.md'
if (Test-Path -LiteralPath $entry) {
    $text = Get-Content -LiteralPath $entry -Raw
    $marker = '<!-- discord-bot-mcp:begin -->'
    if (!$text.Contains($marker)) {
        $routing = @"

<!-- discord-bot-mcp:begin -->
## Sender selection

For personal account messages, keep the Firefox workflow below. For a user
request that explicitly chooses the configured bot, prefer the installed
``discord_bot`` MCP and read [the bot workflow](references/bot-workflow.md).
The bot sends under its own identity and cannot replace personal DM history.
If the bot sender was not chosen and identity matters, ask one concise question.
Never silently switch senders or resend an uncertain MCP send through Firefox.
For a prepared draft only, do not call a bot send tool.
<!-- discord-bot-mcp:end -->

"@
        $position = $text.IndexOf('## Browser and login')
        if ($position -lt 0) { throw 'Installed skill layout changed. Review it before editing.' }
        $updated = $text.Insert($position,$routing)
        $updated = $updated -replace '(?m)^description: Quickly send or prepare user-requested Discord messages[^\r\n]*', 'description: Send or prepare user-requested Discord direct messages or channel messages through the configured bot MCP when that sender is chosen, or dedicated Firefox for personal messages. Split long text and verify delivery without duplicate submissions.'
        [void](New-Item -ItemType Directory -Path (Join-Path $skill 'references') -Force)
        Copy-Item -LiteralPath (Join-Path $source 'integration\bot-workflow.md') -Destination (Join-Path $skill 'references\bot-workflow.md')
        if ((Get-Content -LiteralPath $entry -Raw) -cne $text) { throw 'Skill changed concurrently. Review before retrying.' }
        [IO.File]::WriteAllText($entry, $updated, (New-Object Text.UTF8Encoding($false)))
    }
}
Write-Output 'Discord bot MCP installed and registered. No bot token or Discord message was submitted. No autostart is needed for stdio MCP.'
