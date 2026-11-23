import { createHash } from 'node:crypto';
import { mkdir, open, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';

export function snowflake(value) {
  if (typeof value !== 'string' || !/^[0-9]{17,20}$/.test(value)) throw Error('Expected a Discord snowflake ID as a string.');
  return value;
}

export function splitMessage(content, max = 1800) {
  if (typeof content !== 'string' || !content.trim() || content.length > 100000) throw Error('Message must contain 1 to 100000 UTF-16 units.');
  if (content.length <= max) return [content];
  const pieces = [];
  let part = '';
  for (const {segment} of new Intl.Segmenter(undefined, {granularity:'grapheme'}).segment(content)) {
    if (segment.length > max - 24) throw Error('A single grapheme exceeds the message limit.');
    if (part.length + segment.length > max - 24) { pieces.push(part); part = ''; }
    part += segment;
  }
  if (part) pieces.push(part);
  return pieces.map((piece, i) => `(${i+1}/${pieces.length}) ${piece}`);
}

const hash = value => createHash('sha256').update(value).digest('hex');

export function createDiscordClient({token = process.env.DISCORD_BOT_TOKEN, fetchImpl = globalThis.fetch} = {}) {
  let bot;
  let blockedUntil = 0;
  async function request(method, path, body) {
    if (!token || /\s/.test(token)) throw Error('A bot token is required. Use the local secure setup; never supply a personal account token.');
    if (Date.now() < blockedUntil) throw Error(`Discord rate limit: wait ${Math.ceil((blockedUntil-Date.now())/1000)} seconds before another request.`);
    const response = await fetchImpl(`https://discord.com/api/v10${path}`, {
      method, redirect:'error', signal:AbortSignal.timeout(15000),
      headers:{Authorization:`Bot ${token}`, 'Content-Type':'application/json', 'User-Agent':'DiscordBot (https://github.com/HoppeStudios/discord-mcp-for-codex, 0.2.0)'},
      body:body === undefined ? undefined : JSON.stringify(body)
    });
    const result = await response.json().catch(() => ({}));
    const seconds = Number(response.status === 429 ? result.retry_after ?? response.headers.get('Retry-After') : response.headers.get('X-RateLimit-Remaining') === '0' ? response.headers.get('X-RateLimit-Reset-After') : 0);
    if (Number.isFinite(seconds) && seconds > 0) blockedUntil = Date.now() + seconds * 1000;
    if (!response.ok) throw Error(`Discord API ${response.status}${response.status === 429 ? `; retry after ${Number.isFinite(seconds) ? seconds : 'the indicated'} seconds` : ''}. No automatic resend was attempted.`);
    return result;
  }
  async function identity() {
    if (!bot) {
      const value = await request('GET', '/users/@me');
      if (value.bot !== true) throw Error('Refusing a non-bot Discord identity.');
      bot = value;
    }
    return bot;
  }
  return {request, identity};
}

export async function sendSafely({client, channelId, content, requestId, receiptDir, allowSend = process.env.DISCORD_ALLOW_SEND === '1'}) {
  if (!allowSend) throw Error('Sending is disabled. Enable DISCORD_ALLOW_SEND=1 only for an authorized bot setup.');
  snowflake(channelId);
  if (typeof requestId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(requestId)) throw Error('A stable request_id (1 to 120 safe characters) is required.');
  const parts = splitMessage(content);
  const identity = await client.identity();
  const root = receiptDir || process.env.DISCORD_RECEIPT_DIR || join(process.env.LOCALAPPDATA || join(homedir(), '.local', 'share'), 'CodexDiscord', 'bot_requests');
  await mkdir(root, {recursive:true, mode:0o700});
  const key = hash(`${identity.id}:${requestId}`);
  const file = join(root, `${key}.json`);
  const lock = `${file}.lock`;
  let handle;
  try { handle = await open(lock, 'wx', 0o600); }
  catch { throw Error('Request is locked by another operation or an interrupted process. Inspect the receipt and actual history before manual recovery.'); }
  try {
    const fingerprint = hash(JSON.stringify({bot:identity.id, channelId, content}));
    let receipt;
    try { receipt = JSON.parse(await readFile(file, 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (receipt && receipt.fingerprint !== fingerprint) throw Error('request_id was already used for different content or destination.');
    receipt ||= {fingerprint, channelId, botId:identity.id, parts:[]};
    const persist = async () => {
      await writeFile(`${file}.tmp`, JSON.stringify(receipt, null, 2), {mode:0o600});
      await rename(`${file}.tmp`, file);
    };
    for (const [index, part] of parts.entries()) {
      let item = receipt.parts[index];
      if (item?.state === 'pending') return {status:'delivery_unknown', channel_id:channelId, part:index+1, message_ids:receipt.parts.map(x=>x.id).filter(Boolean)};
      if (!item) {
        item = {state:'pending', contentHash:hash(part)};
        receipt.parts[index] = item;
        await persist();
        const nonce = hash(`${identity.id}:${requestId}:${index}`).slice(0,24);
        let posted;
        try {
          posted = await client.request('POST', `/channels/${channelId}/messages`, {content:part, allowed_mentions:{parse:[], replied_user:false}, nonce, enforce_nonce:true});
        } catch {
          return {status:'delivery_unknown', channel_id:channelId, part:index+1, message_ids:receipt.parts.map(x=>x.id).filter(Boolean), detail:'Submission failed or was rate limited. Inspect actual history before recovery. Do not use a new request_id to retry.'};
        }
        if (posted.channel_id !== channelId || posted.content !== part || posted.author?.id !== identity.id) throw Error('Unexpected send response. Receipt remains pending; inspect actual history.');
        item.id = snowflake(posted.id);
        item.state = 'submitted';
        await persist();
      }
      const fetched = await client.request('GET', `/channels/${channelId}/messages/${snowflake(item.id)}`);
      if (fetched.channel_id !== channelId || fetched.content !== part || fetched.author?.id !== identity.id) throw Error('Message readback failed. Do not resend; inspect the recorded message ID.');
      item.state = 'verified';
      await persist();
    }
    return {status:'verified_by_api', channel_id:channelId, bot_id:identity.id, message_ids:receipt.parts.map(x=>x.id), parts:parts.length};
  } finally { await handle.close(); await rm(lock); }
}
