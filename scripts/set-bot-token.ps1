$ErrorActionPreference = 'Stop'
$dir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexDiscord'
[void](New-Item -ItemType Directory -Path $dir -Force)
$secret = Read-Host 'Discord BOT token (hidden, never paste it into chat)' -AsSecureString
if ($secret.Length -eq 0) { throw 'No token entered. Nothing saved.' }
$file = Join-Path $dir 'bot-token.dpapi'
$secret | ConvertFrom-SecureString | Set-Content -LiteralPath $file -Encoding ASCII
# Limit the encrypted file to this Windows user and SYSTEM.
$acl = New-Object Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule([Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'Allow')))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule('SYSTEM', 'FullControl', 'Allow')))
Set-Acl -LiteralPath $file -AclObject $acl
Write-Output 'Bot token saved encrypted for this Windows account. No Discord request was sent.'
