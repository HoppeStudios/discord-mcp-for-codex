import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm, readFile, readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createDiscordClient, sendSafely, splitMessage, snowflake} from '../safe-messaging.mjs';
import {callTool} from '../discord-mcp.mjs';

const botId='111111111111111111', channelId='222222222222222222', messageId='333333333333333333';
function fixture() {
  let posts=0, gets=0, last, failPost=false, failRead=false;
  return {client:{identity:async()=>({id:botId,bot:true}),request:async(method,path,body)=>{
    if(method==='POST') {posts++;last={id:messageId,channel_id:channelId,content:body.content,author:{id:botId},body}; if(failPost)throw Error('network interrupted'); return last;}
    gets++;if(failRead)throw Error('read failed');return last;
  }},get posts(){return posts},get gets(){return gets},get last(){return last},set failPost(x){failPost=x},set failRead(x){failRead=x}};
}
async function withDir(fn) {const dir=await mkdtemp(join(tmpdir(),'discord-mcp-test-'));try{await fn(dir)}finally{await rm(dir,{recursive:true,force:true})}}
const args=(client,receiptDir,extra={})=>({client,receiptDir,channelId,content:'Hi @everyone 👨‍👩‍👧‍👦\nŽluťoučký',requestId:'test-operation',allowSend:true,...extra});

test('Unicode splitting preserves exact text, graphemes and numbering bounds',()=>{
  const content=('Ž 👨‍👩‍👧‍👦 e\u0301\n').repeat(1000);
  const parts=splitMessage(content);
  assert.ok(parts.length>1);assert.ok(parts.every(x=>x.length<=1800));
  assert.equal(parts.map(x=>x.replace(/^\(\d+\/\d+\) /,'')).join(''),content);
  assert.throws(()=>splitMessage('a'+'\u0301'.repeat(2000)+'b'.repeat(2000)));
});
test('IDs reject route injection and unsafe inputs before networking',async()=>{
  for(const id of ['../users/@me','22/messages','',2222,'1'])assert.throws(()=>snowflake(id));
  for(const arguments_ of [{channel_id:'../../users/@me'},{channel_id:channelId,limit:0},{channel_id:channelId,limit:1.5},{channel_id:channelId,other:'value'}])await assert.rejects(callTool({name:'read_messages',arguments:arguments_}));
});
test('disabled writes do not touch API or receipts',()=>withDir(async dir=>{
  const f=fixture();await assert.rejects(sendSafely(args(f.client,dir,{allowSend:false})));assert.equal(f.posts,0);assert.deepEqual(await readdir(dir),[]);
}));
test('channel creation stays disabled independently of message sending',async()=>{
  delete process.env.DISCORD_ALLOW_CHANNEL_CREATE;
  await assert.rejects(callTool({name:'create_text_channel',arguments:{guild_id:channelId,name:'example'}}),/disabled/);
});
test('receipt exists before POST, mentions suppressed, GET verifies, retry does not POST',()=>withDir(async dir=>{
  const f=fixture(), real=f.client.request;
  f.client.request=async(method,path,body)=>{if(method==='POST') {const files=(await readdir(dir)).filter(x=>x.endsWith('.json'));assert.equal(files.length,1);assert.equal(JSON.parse(await readFile(join(dir,files[0]),'utf8')).parts[0].state,'pending');}return real(method,path,body)};
  assert.equal((await sendSafely(args(f.client,dir))).status,'verified_by_api');
  assert.deepEqual(f.last.body.allowed_mentions,{parse:[],replied_user:false});assert.equal(f.last.body.enforce_nonce,true);
  await sendSafely(args(f.client,dir));assert.equal(f.posts,1);assert.equal(f.gets,2);
  await assert.rejects(sendSafely(args(f.client,dir,{content:'changed'})));assert.equal(f.posts,1);
}));
test('uncertain POST stays unknown across retries',()=>withDir(async dir=>{
  const f=fixture();f.failPost=true;assert.equal((await sendSafely(args(f.client,dir))).status,'delivery_unknown');f.failPost=false;
  assert.equal((await sendSafely(args(f.client,dir))).status,'delivery_unknown');assert.equal(f.posts,1);
}));
test('failed readback resumes using known ID without resending',()=>withDir(async dir=>{
  const f=fixture();f.failRead=true;await assert.rejects(sendSafely(args(f.client,dir)));f.failRead=false;
  assert.equal((await sendSafely(args(f.client,dir))).status,'verified_by_api');assert.equal(f.posts,1);
}));
test('multipart message sends once per piece and resumes all verified IDs',()=>withDir(async dir=>{
  const f=fixture(), content='🙂 abc\n'.repeat(1000);
  // Keep separate API messages for exact ID readback.
  const messages=new Map();let posts=0;
  f.client.request=async(method,path,body)=>{if(method==='POST'){const id=String(BigInt(messageId)+BigInt(posts++));const m={id,channel_id:channelId,content:body.content,author:{id:botId}};messages.set(id,m);return m;}return messages.get(path.split('/').at(-1));};
  const a=args(f.client,dir,{content});const first=await sendSafely(a);const second=await sendSafely(a);
  assert.equal(posts,splitMessage(content).length);assert.deepEqual(first.message_ids,second.message_ids);
}));
test('concurrent operations cannot send the same request twice',()=>withDir(async dir=>{
  const f=fixture();let release,entered;const waiting=new Promise(r=>release=r), started=new Promise(r=>entered=r),real=f.client.request;
  f.client.request=async(...a)=>{if(a[0]==='POST'){entered();await waiting;}return real(...a)};
  const one=sendSafely(args(f.client,dir));await started;await assert.rejects(sendSafely(args(f.client,dir)),/locked/);release();await one;assert.equal(f.posts,1);
}));
test('bot-only identity, timeout, fixed origin, no redirects and secret-free HTTP errors',async()=>{
  let init,url;
  const client=createDiscordClient({token:'fixture-secret',fetchImpl:async(u,i)=>{url=u;init=i;return new Response(JSON.stringify({id:botId,bot:false}),{status:200})}});
  await assert.rejects(client.identity(),/non-bot/);assert.equal(url,'https://discord.com/api/v10/users/@me');assert.equal(init.redirect,'error');assert.ok(init.signal);assert.equal(init.headers.Authorization,'Bot fixture-secret');
  const failed=createDiscordClient({token:'fixture-secret',fetchImpl:async()=>new Response(JSON.stringify({message:'fixture-secret'}),{status:401})});
  await assert.rejects(failed.identity(),e=>!e.message.includes('fixture-secret'));
});
test('429 blocks following calls and is never retried automatically',async()=>{
  let calls=0;const client=createDiscordClient({token:'fixture',fetchImpl:async()=>{calls++;return new Response(JSON.stringify({retry_after:10}),{status:429})}});
  await assert.rejects(client.identity(),/429/);await assert.rejects(client.identity(),/rate limit/);assert.equal(calls,1);
});
