"""Personal Discord web UI adapter. Never reads account secrets or calls account APIs."""
import asyncio
from contextlib import asynccontextmanager, redirect_stdout
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata


def load_sender():
    path = Path(os.environ['DISCORD_BROWSER_HELPER']).resolve()
    expected = os.environ['DISCORD_BROWSER_HELPER_SHA256']
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Browser helper changed. Review and reinstall the adapter before use.')
    spec = importlib.util.spec_from_file_location('discord_browser_sender', path)
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    return sender


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


IDENTITY = '''() => {
  const panels=[...document.querySelectorAll('section[aria-label="User status and settings"],section[class*="panels_"]')].filter(e=>e.getClientRects().length);
  const accounts=[...new Set(panels)].map(e=>{const lines=e.innerText.split('\\n').map(s=>s.trim()).filter(Boolean);const avatar=e.querySelector('img[src*="/avatars/"]')?.getAttribute('src')||'';return {display_name:lines[0],username:lines[1],avatar_user_id:avatar.match(/\\/avatars\\/(\\d+)\\//)?.[1]||null};});
  return {url:location.href,login:location.pathname.startsWith('/login'),accounts};
}'''


async def identity(sender, session, expected=None):
    state = await sender.evaluate(session, IDENTITY)
    if state['login']:
        raise RuntimeError('login_required: sign in manually to the dedicated Firefox profile. No token fallback exists.')
    accounts = state['accounts']
    if len(accounts) != 1 or not re.fullmatch(r'[a-z0-9_.]{2,32}', accounts[0].get('username') or ''):
        raise RuntimeError('Visible sender identity is missing or ambiguous. No input was attempted.')
    account = accounts[0]
    if expected is not None and account['username'] != expected:
        raise RuntimeError('sender_mismatch: the visible logged-in account differs from expected_sender.')
    return account


class BrowserAdapter:
    def __init__(self, sender, data_dir):
        self.sender = sender
        self.data_dir = Path(data_dir)

    @asynccontextmanager
    async def session(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.types import ElicitResult
        self.data_dir.mkdir(parents=True, exist_ok=True)
        lock = self.data_dir / 'personal-adapter.lock'
        try:
            handle = lock.open('x', encoding='utf-8')
        except FileExistsError:
            raise RuntimeError('profile_busy: another adapter operation or an interrupted worker owns the lock. Inspect before manual recovery.')
        try:
            cfg = self.sender.config()['mcp_servers']['firefox_existing']
            if '--headless' not in cfg.get('args', []):
                raise RuntimeError('The registered dedicated Firefox must use background headless mode.')
            self.sender.idle_profile(cfg)
            async def decline(context, params):
                return ElicitResult(action='decline')
            params = StdioServerParameters(command=cfg['command'], args=cfg.get('args', []), env={**os.environ, **cfg.get('env', {})}, cwd=cfg.get('cwd'))
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w, elicitation_callback=decline) as session:
                    await session.initialize()
                    try:
                        yield session
                    finally:
                        await self.sender.call(session, 'close_firefox_session', {})
        finally:
            handle.close()
            lock.unlink()

    async def open_page(self, session, url, expected=None):
        if url != 'https://discord.com/channels/@me':
            self.sender.validate_url(url)
        await self.sender.call(session, 'new_page', {'url':url, 'wait':'interactive'})
        deadline = time.monotonic() + 25
        while True:
            state = await self.sender.evaluate(session, IDENTITY)
            if state['login']:
                raise RuntimeError('login_required: manual sign-in to the dedicated profile is required.')
            populated = len(state['accounts']) == 1 and re.fullmatch(r'[a-z0-9_.]{2,32}', state['accounts'][0].get('username') or '')
            if state['url'].rstrip('/') == url.rstrip('/') and populated:
                return await identity(self.sender, session, expected)
            if time.monotonic() >= deadline:
                raise RuntimeError('The Discord web UI did not expose a visible account within the bounded wait.')
            await asyncio.sleep(.2)

    async def personal_identity(self):
        async with self.session() as session:
            return {'status':'visible_account_verified', 'sender':await self.open_page(session, 'https://discord.com/channels/@me'), 'transport':'Firefox web UI'}

    async def find_conversations(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 100:
            raise ValueError('Use a recipient name from 1 to 100 characters.')
        async with self.session() as session:
            account = await self.open_page(session, 'https://discord.com/channels/@me')
            links = await self.sender.evaluate(session, '''() => [...document.querySelectorAll('a[href^="/channels/@me/"]')].filter(e=>e.getClientRects().length).map(e=>({url:'https://discord.com'+e.getAttribute('href'),name:e.innerText.split('\\n')[0].trim(),label:e.getAttribute('aria-label')}))''')
            matches = [dict(row, exact=normalize(row['name']) == normalize(query.strip())) for row in links if normalize(query.strip()) in normalize(row['name'])]
            return {'sender':account, 'matches':matches[:50], 'scope':'visible recent DM links only'}

    async def inspect_conversation(self, channel_url, expected_sender):
        self.sender.validate_url(channel_url)
        async with self.session() as session:
            account = await self.open_page(session, channel_url, expected_sender)
            deadline = time.monotonic() + 20
            while True:
                state = await self.sender.evaluate(session, self.sender.STATE)
                if state['url'].rstrip('/') == channel_url.rstrip('/') and len(state['editors']) == 1:
                    editor = state['editors'][0]
                    return {'status':'inspected', 'sender':account, 'channel_url':channel_url, 'composer_label':editor['label'], 'draft_present':not self.sender.empty(editor['text'])}
                if time.monotonic() >= deadline:
                    raise RuntimeError('Conversation composer is missing or ambiguous.')
                await asyncio.sleep(.2)

    async def deliver(self, channel_url, composer_label, expected_sender, content, request_id, prepare=False):
        self.sender.validate_url(channel_url)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', request_id):
            raise ValueError('Use one stable request_id with 1 to 120 safe characters.')
        if len(content) > 100000:
            raise ValueError('Content exceeds the local message budget.')
        self.sender.split_text(content)
        if not composer_label or not re.fullmatch(r'[a-z0-9_.]{2,32}', expected_sender):
            raise ValueError('The inspected composer label and expected sender username are required.')
        async with self.session() as session:
            account = await self.open_page(session, channel_url, expected_sender)
            key = hashlib.sha256(request_id.encode()).hexdigest()
            receipt = self.data_dir / (key + '.json')
            sender_file = self.data_dir / (key + '.sender.json')
            if sender_file.exists():
                if json.loads(sender_file.read_text('utf-8'))['username'] != expected_sender:
                    raise RuntimeError('request_id belongs to a different sender. Do not retry under another ID.')
            elif receipt.exists():
                raise RuntimeError('legacy_receipt: inspect the existing request and history before recovery. Do not evade it.')
            else:
                sender_file.write_text(json.dumps({'username':expected_sender}), encoding='utf-8')
            original_call = self.sender.call
            async def guarded_call(target, name, args):
                if name == 'press_key' and args.get('key') == 'Enter':
                    await identity(self.sender, target, expected_sender)
                    await self.sender.ready(target, channel_url, composer_label, False)
                return await original_call(target, name, args)
            self.sender.call = guarded_call
            try:
                # The helper's progress output must not corrupt MCP's JSON stdout.
                with redirect_stdout(sys.stderr):
                    result = await self.sender.send(session, channel_url, composer_label, content, request_id, self.data_dir, prepare=prepare)
            finally:
                self.sender.call = original_call
            ids = []
            if receipt.exists():
                ids = [p['message_id'] for p in json.loads(receipt.read_text('utf-8'))['parts'] if 'message_id' in p]
            return {**result, 'sender':account, 'channel_url':channel_url, 'message_ids':ids}

    async def verify_delivery(self, channel_url, composer_label, expected_sender, content, request_id):
        """Inspect an existing pending receipt using visible history only. Never submit."""
        self.sender.validate_url(channel_url)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', request_id):
            raise ValueError('Use the original stable request_id.')
        key = hashlib.sha256(request_id.encode()).hexdigest()
        path = self.data_dir / (key + '.json')
        receipt = json.loads(path.read_text('utf-8'))
        digest = hashlib.sha256((channel_url + '\0' + content).encode()).hexdigest()
        if receipt['content_sha256'] != digest:
            raise RuntimeError('Receipt does not match this exact destination and content.')
        sender_file = self.data_dir / (key + '.sender.json')
        if json.loads(sender_file.read_text('utf-8'))['username'] != expected_sender:
            raise RuntimeError('Receipt sender differs. No recovery attempted.')
        parts = self.sender.split_text(content)
        if len(parts) != len(receipt['parts']):
            raise RuntimeError('Receipt part count differs.')
        async with self.session() as session:
            account = await self.open_page(session, channel_url, expected_sender)
            await self.sender.ready(session, channel_url, composer_label, False)
            verified = []
            for part, record in zip(parts, receipt['parts']):
                if record['status'] not in ('submission_pending', 'persisted_after_reload'):
                    raise RuntimeError('An unsubmitted part cannot be marked delivered.')
                wanted = record.get('message_id')
                before = record.get('prior_message_ids', [])
                async def candidate(wanted_id=None):
                    deadline = time.monotonic() + 20
                    while True:
                        data = json.dumps({'text':part, 'before':before, 'id':wanted_id})
                        rows = await self.sender.evaluate(session, '''() => {const p=''' + data + ''';return [...document.querySelectorAll('[id^="message-content-"]')].filter(e=>e.innerText===p.text&&(p.id?e.id===p.id:!p.before.includes(e.id))).map(e=>{const li=e.closest('li');let header=li;for(let i=0;i<50&&header&&!header.querySelector('[id^="message-username-"]');i++)header=header.previousElementSibling;const name=header?.querySelector('[class*="username_"]')?.innerText;const avatar=header?.querySelector('img[src*="/avatars/"]')?.getAttribute('src')||'';return {id:e.id,author_name:name,author_id:avatar.match(/\\/avatars\\/(\\d+)\\//)?.[1]||null,failed:!!li?.querySelector('[aria-label*="Failed"],[aria-label*="Retry"]')};});}''')
                        if rows:
                            if len(rows) != 1 or rows[0]['failed']:
                                raise RuntimeError('History match is ambiguous or failed. No recovery was recorded.')
                            row = rows[0]
                            own = row['author_id'] == account['avatar_user_id'] if account.get('avatar_user_id') else row.get('author_name') == account['display_name']
                            if not own:
                                raise RuntimeError('History author could not be verified as the visible sender.')
                            return row['id']
                        if time.monotonic() >= deadline:
                            raise RuntimeError('delivery_unknown: no unique matching history message. No resend attempted.')
                        await asyncio.sleep(.2)
                message_id = await candidate(wanted)
                await self.sender.call(session, 'navigate_page', {'url':channel_url, 'wait':'interactive'})
                await self.sender.ready(session, channel_url, composer_label, False)
                await identity(self.sender, session, expected_sender)
                await candidate(message_id)
                verified.append(message_id)
            for record, message_id in zip(receipt['parts'], verified):
                record.update(status='persisted_after_reload', message_id=message_id, recovery='verified_history_without_resend')
            self.sender.save_receipt(path, receipt)
            return {'status':'persisted_after_reload', 'submitted_now':0, 'recovered_from_history':True, 'sender':account, 'channel_url':channel_url, 'message_ids':verified}


def main():
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    if os.name == 'nt':
        os.environ['PSModulePath'] = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/Modules')
    sender = load_sender()
    adapter = BrowserAdapter(sender, os.environ['DISCORD_BROWSER_DATA_DIR'])
    # Serialize all calls in this worker. The filesystem lock also covers other workers.
    gate = asyncio.Lock()
    mcp = FastMCP('discord-personal-browser')
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

    async def execute(operation):
        async with gate:
            try:
                return await operation
            except Exception as error:
                raise RuntimeError(' | '.join(sender.failure_reasons(error))) from None

    @mcp.tool(annotations=read)
    async def personal_identity() -> dict:
        """Read the visible signed-in account through the dedicated Firefox web UI. No tokens or account API."""
        return await execute(adapter.personal_identity())

    @mcp.tool(annotations=read)
    async def find_conversations(query: str) -> dict:
        """Find matching visible recent DM links. Exact names can still be ambiguous. Do not invent IDs."""
        return await execute(adapter.find_conversations(query))

    @mcp.tool(annotations=read)
    async def inspect_conversation(channel_url: str, expected_sender: str) -> dict:
        """Verify the visible personal sender, exact route, composer label and presence of an existing draft without editing it."""
        return await execute(adapter.inspect_conversation(channel_url, expected_sender))

    @mcp.tool(annotations=write)
    async def prepare_personal_message(channel_url: str, composer_label: str, expected_sender: str, content: str, request_id: str) -> dict:
        """Prepare only the first split part in an empty composer. Preserve existing drafts. Never submit."""
        return await execute(adapter.deliver(channel_url, composer_label, expected_sender, content, request_id, prepare=True))

    @mcp.tool(annotations=write)
    async def send_personal_message(channel_url: str, composer_label: str, expected_sender: str, content: str, request_id: str) -> dict:
        """Send only a user-authorized personal message via Discord web UI. Verify sender and inspected destination, preserve drafts, split long text, persist receipts, submit each part once and verify the same history ID after reload. Reuse request_id on retries. Unknown delivery stops and must not be retried under a new ID or identity."""
        return await execute(adapter.deliver(channel_url, composer_label, expected_sender, content, request_id))

    @mcp.tool(annotations=read)
    async def verify_personal_delivery(channel_url: str, composer_label: str, expected_sender: str, content: str, request_id: str) -> dict:
        """Inspect an existing uncertain receipt without resending. Require one exact new history match by the visible sender and the same message ID after another reload. Preserve drafts and stop on ambiguity."""
        return await execute(adapter.verify_delivery(channel_url, composer_label, expected_sender, content, request_id))

    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
