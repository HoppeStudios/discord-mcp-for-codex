# Discord MCP for Codex

A local stdio MCP server for a Discord **bot account**. Read channels and send
verified messages as the bot. No npm dependencies, gateway, telemetry, network
listener or startup updater. Requires a maintained Node.js version at least
24.22.3 and a legitimate Discord bot token.

This HoppeStudios fork starts from
[sashakang/discord-mcp-for-codex](https://github.com/sashakang/discord-mcp-for-codex)
at `b826bfd133cda45aab067090ca1a0ee92117f7aa`.
The exact original commit is recorded by Git history. The original MIT license
and Sasha Kang's copyright notice are retained in [LICENSE](LICENSE).

## Identity and access

The bot has its own name, permissions and DM conversations. It cannot read your
personal account DM history or send as you. Never use a personal account token.
Discord documents [bot authentication](https://docs.discord.com/developers/reference#authentication)
and [prohibits self bots](https://support.discord.com/hc/en-us/articles/115002192352).

Create an application in the [Discord Developer Portal](https://discord.com/developers/applications),
add its bot and save the token locally. Invite it only to an authorized server.
For ordinary messaging grant View Channels, Send Messages and Read Message
History. For thread messages also grant Send Messages in Threads. Do not grant
Administrator or Manage Channels for ordinary messaging. Reading other people's
message content may require the Message Content privileged intent. Bot DMs depend
on recipient privacy, Discord policy and shared context. They are not guaranteed.

## Windows installation

Review this source and run the tests before installing. Obtain an exact supported
Node release from [nodejs.org](https://nodejs.org/en/download). Verify the official
SHA256 and Windows signature. Supply the absolute path to that reviewed node.exe:

```powershell
.\scripts\install-windows.ps1 -RuntimeExe 'C:\path\to\reviewed\node.exe'
```

The installer copies the reviewed payload, records file and runtime hashes and
adds `discord_bot` to the existing Codex config without embedding a token. It
refuses an existing registration or active installed process. It adds bot routing
to an existing `discord-messages` skill and preserves its Firefox sender and
scripts. It creates no backups, scheduled tasks or Windows Startup entries.
MCP stdio starts on demand through its registration. Updates require review and
replacement after active sessions finish, followed by the same health checks.

Enter the token in a local PowerShell terminal using the installed setup script:

```powershell
& "$([Environment]::GetFolderPath('MyDocuments'))\Codex\tools\mcp\discord-bot-mcp-0.2.0\set-bot-token.ps1"
```

The prompt hides input. Windows DPAPI encrypts the secret for the current Windows
account. The encrypted file is restricted to that account and SYSTEM and lives
outside Git and Codex config. The launcher decrypts it only into the child
process environment. Never paste tokens into chat, source, issues or logs.
Reconnect the MCP and use `bot_identity` for a read only authentication check.
Installing and verifying the server does not authorize a probe message.

## Other clients

Launch `node /absolute/path/discord-mcp.mjs` over stdio. Provide
`DISCORD_BOT_TOKEN` through a local secret manager. Sending is disabled by default.
Set `DISCORD_ALLOW_SEND=1` for an authorized bot configuration. Channel creation
is separately disabled unless `DISCORD_ALLOW_CHANNEL_CREATE=1`. The Windows
registration enables send capability and keeps channel creation disabled.
Tool availability is not permission to send unsolicited messages.

## Tools and delivery

Read tools are `bot_identity`, `list_guilds`, `list_channels`, `get_channel` and
`read_messages`. `create_dm_channel` and `read_dm_messages` can create a remote bot
DM channel. `send_message` and `send_dm` require content, destination and a stable
`request_id`. `create_text_channel` is available behind its separate gate.

Before sending, verify the bot and destination with `get_channel`. Send tools
split text into numbered messages of at most 1800 UTF-16 units while preserving
graphemes. All mentions are suppressed. They persist a receipt before each POST,
use a deterministic Discord nonce and verify the returned IDs through fresh GET
requests. `verified_by_api` means exact bot, channel and content readback passed.
It does not mean that a recipient read the message.

Repeated successful requests recheck existing message IDs without posting again.
A pending receipt returns `delivery_unknown`. A failed readback resumes using
the recorded ID. Inspect actual history before recovering unknown submissions
or stale locks. Never choose another request ID or transport to evade them.
The per request lock prevents concurrent duplicate submission. Local receipts
contain hashes and IDs rather than message text and are stored under the user's
local data directory, configurable with `DISCORD_RECEIPT_DIR`.

Requests have a fifteen second timeout and refuse redirects. Numeric snowflake
validation prevents path injection. Discord rate limit headers block subsequent
calls until the indicated time. Mutating requests are never retried automatically.
There is no claim of exactly once delivery across arbitrary failures.

See [the skill workflow](integration/bot-workflow.md) for sender selection,
preparation, recipient checks and uncertain delivery handling.

## Validation

```sh
npm test
npm run smoke:test
```

These local tests use mock Discord responses and temporary receipt directories.
They cover Unicode splitting, destination validation, disabled writes, durable
receipts, mention suppression, readback, multipart sends, retries, concurrency,
bot identity, timeouts, redirect refusal and rate limits. The smoke test checks
the actual stdio startup and tool discovery. Neither sends a Discord message.
Live bot authentication and delivery require a configured bot and separate
authorization for any actual message. Source review and malware scans provide
bounded evidence, not a guarantee that all vulnerabilities are absent.
