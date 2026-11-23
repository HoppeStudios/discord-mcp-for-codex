param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [string]$InstallDir = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Codex\tools\mcp\discord-personal-browser-0.3.1'),
    [string]$PreviousInstallDir,
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' })
)
$ErrorActionPreference='Stop'
$running=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and $_.CommandLine.Contains($InstallDir) }
if ($running) { throw 'The personal Discord adapter is active. Finish it before replacing files.' }
$data=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexDiscord\fast_requests'
$extra=@()
if($PreviousInstallDir){$extra=@('--previous-install-dir',$PreviousInstallDir)}
& $PythonExe -B -X utf8 (Join-Path $PSScriptRoot 'install-browser.py') --codex-home $CodexHome --install-dir $InstallDir --data-dir $data @extra
if ($LASTEXITCODE -ne 0) { throw 'Browser adapter installation failed.' }
