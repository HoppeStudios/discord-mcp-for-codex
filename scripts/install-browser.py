"""Install the reviewed browser adapter without changing existing MCP settings."""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib


def install(args):
    source = Path(__file__).resolve().parents[1]
    codex = Path(args.codex_home).resolve()
    dest = Path(args.install_dir).resolve()
    config_file = codex / 'config.toml'
    before = config_file.read_text('utf-8')
    parsed = tomllib.loads(before)
    current = parsed.get('mcp_servers', {}).get('discord_personal')
    if current and not args.previous_install_dir:
        raise RuntimeError('discord_personal already exists. Review its registration before replacement.')
    skill = codex / 'skills/discord-messages'
    entry = skill / 'SKILL.md'
    text = entry.read_text('utf-8')
    helper = skill / 'scripts/send_discord_message.py'
    helper_hash = hashlib.sha256(helper.read_bytes()).hexdigest()
    marker_start, marker_end = '<!-- discord-bot-mcp:begin -->', '<!-- discord-bot-mcp:end -->'
    if text.count(marker_start) != 1 or text.count(marker_end) != 1:
        raise RuntimeError('Skill routing differs from the reviewed version. Inspect before editing.')
    routing = '''<!-- discord-bot-mcp:begin -->
## Sender selection

Use the personal account by default. Prefer the registered `discord_personal`
MCP and read [the personal browser workflow](references/browser-workflow.md).
It operates the ordinary Discord web UI through the dedicated Firefox profile.
It is not an official personal account API and never reads account tokens.
Keep the Firefox helper below as a fallback when the adapter is unavailable.
Use `discord_bot` only when the user explicitly chooses a bot sender, following
[the bot workflow](references/bot-workflow.md). Never silently switch identities
or evade an uncertain delivery receipt through another transport.
<!-- discord-bot-mcp:end -->'''
    start = text.index(marker_start)
    end = text.index(marker_end) + len(marker_end)
    updated = text[:start] + routing + text[end:]
    import re
    updated = re.sub(r'(?m)^description: [^\r\n]*', 'description: Send or prepare user-requested Discord messages from the personal account through the dedicated Firefox browser MCP adapter by default. Use bot MCP only when explicitly chosen. Split long text and verify exact delivery without duplicates.', updated, count=1)
    dest.mkdir(parents=True, exist_ok=True)
    for name, origin in [('browser_adapter.py', source/'browser_adapter.py'), ('launch-browser.py', source/'scripts/launch-browser.py'), ('LICENSE', source/'LICENSE')]:
        shutil.copyfile(origin, dest/name)
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    files = [dest/'browser_adapter.py', dest/'LICENSE', helper, Path(sys.executable).resolve()]
    data_dir = Path(args.data_dir).resolve()
    manifest = {'version':'0.3.1', 'files':[{'path':str(p),'sha256':digest(p)} for p in files], 'helper':str(helper), 'helper_sha256':helper_hash, 'data_dir':str(data_dir), 'mcp_version':version('mcp')}
    (dest/'manifest.json').write_text(json.dumps(manifest, indent=2), 'utf-8')
    # TOML literal strings are used only for reviewed paths, never credentials.
    paths = [str(Path(sys.executable).resolve()), str(dest/'launch-browser.py')]
    if any("'" in p or '\n' in p for p in paths):
        raise RuntimeError('A path requires TOML escaping. Review before installation.')
    registration = f"\n[mcp_servers.discord_personal]\ncommand = '{paths[0]}'\nargs = ['-B', '-X', 'utf8', '{paths[1]}']\n"
    if current:
        old = str(Path(args.previous_install_dir).resolve() / 'launch-browser.py')
        if current.get('command') != paths[0] or current.get('args') != ['-B','-X','utf8',old] or before.count("'"+old+"'") != 1:
            raise RuntimeError('Previous registration differs. Inspect before upgrading.')
        new_config = before.replace("'"+old+"'", "'"+paths[1]+"'", 1)
    else:
        new_config = before.rstrip() + '\n' + registration
    checked = tomllib.loads(new_config)
    checked['mcp_servers'].pop('discord_personal')
    if current:
        parsed['mcp_servers'].pop('discord_personal')
    if checked != parsed:
        raise RuntimeError('Unrelated configuration would change.')
    if config_file.read_text('utf-8') != before or entry.read_text('utf-8') != text or digest(helper) != helper_hash:
        raise RuntimeError('Source settings changed during setup. Inspect concurrent work.')
    references = skill / 'references'
    references.mkdir(exist_ok=True)
    shutil.copyfile(source/'integration/browser-workflow.md', references/'browser-workflow.md')
    config_file.write_text(new_config, 'utf-8')
    entry.write_text(updated, 'utf-8')
    print(json.dumps({'status':'installed', 'mcp':'discord_personal', 'version':'0.3.1', 'mcp_sdk':manifest['mcp_version'], 'helper_unchanged':digest(helper)==helper_hash, 'messages_sent':0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', required=True)
    parser.add_argument('--install-dir', required=True)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--previous-install-dir')
    install(parser.parse_args())
