#!/usr/bin/env node

import readline from "node:readline";
import { pathToFileURL } from 'node:url';
import { createDiscordClient, sendSafely, snowflake } from './safe-messaging.mjs';
const client = createDiscordClient();


const SERVER_INFO = {
  name: "local-discord-bot-mcp",
  version: "0.2.0"
};

const tools = [
  {
    name: "bot_identity",
    description: "Get the Discord bot user's identity.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false
    }
  },
  {
    name: "list_guilds",
    description: "List Discord servers the bot can access.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false
    }
  },
  {
    name: "list_channels",
    description: "List channels in a Discord server by guild ID.",
    inputSchema: {
      type: "object",
      properties: {
        guild_id: {
          type: "string",
          description: "Discord guild/server ID."
        }
      },
      required: ["guild_id"],
      additionalProperties: false
    }
  },
  {
    name: "read_messages",
    description: "Read recent messages from a Discord channel by channel ID.",
    inputSchema: {
      type: "object",
      properties: {
        channel_id: {
          type: "string",
          description: "Discord channel ID."
        },
        limit: {
          type: "number",
          description: "Number of messages to read, 1-100.",
          minimum: 1,
          maximum: 100
        }
      },
      required: ["channel_id"],
      additionalProperties: false
    }
  },
  {
    name: "send_message",
    description: "Send a text message to a Discord channel by channel ID.",
    inputSchema: {
      type: "object",
      properties: {
        channel_id: {
          type: "string",
          description: "Discord channel ID."
        },
        content: {
          type: "string",
          description: "Message text to send."
        }
      },
      required: ["channel_id", "content"],
      additionalProperties: false
    }
  },
  {
    name: "create_dm_channel",
    description: "Create or return a direct-message channel with a Discord user by user ID.",
    inputSchema: {
      type: "object",
      properties: {
        user_id: {
          type: "string",
          description: "Discord user ID for the DM recipient."
        }
      },
      required: ["user_id"],
      additionalProperties: false
    }
  },
  {
    name: "send_dm",
    description: "Send a direct message to a Discord user by user ID.",
    inputSchema: {
      type: "object",
      properties: {
        user_id: {
          type: "string",
          description: "Discord user ID for the DM recipient."
        },
        content: {
          type: "string",
          description: "Message text to send."
        }
      },
      required: ["user_id", "content"],
      additionalProperties: false
    }
  },
  {
    name: "read_dm_messages",
    description: "Read recent direct-message messages with a Discord user by user ID.",
    inputSchema: {
      type: "object",
      properties: {
        user_id: {
          type: "string",
          description: "Discord user ID for the DM recipient."
        },
        limit: {
          type: "number",
          description: "Number of messages to read, 1-100.",
          minimum: 1,
          maximum: 100
        }
      },
      required: ["user_id"],
      additionalProperties: false
    }
  },
  {
    name: "create_text_channel",
    description: "Create a text channel in a Discord server by guild ID.",
    inputSchema: {
      type: "object",
      properties: {
        guild_id: {
          type: "string",
          description: "Discord guild/server ID."
        },
        name: {
          type: "string",
          description: "New channel name."
        },
        topic: {
          type: "string",
          description: "Optional channel topic."
        }
      },
      required: ["guild_id", "name"],
      additionalProperties: false
    }
  }
];

for (const tool of tools) {
  const readOnly = ['bot_identity','list_guilds','list_channels','read_messages','get_channel'].includes(tool.name);
  tool.annotations = {readOnlyHint:readOnly, destructiveHint:false, idempotentHint:readOnly, openWorldHint:true};
  if (['send_message','send_dm'].includes(tool.name)) {
    tool.inputSchema.properties.request_id = {type:'string', description:'Stable unique operation ID. Reuse on retries; never replace an uncertain receipt.'};
    tool.inputSchema.required.push('request_id');
    tool.description += ' Posts as the bot. Splits long text, suppresses all mentions, persists receipts and verifies message IDs. Requires user authorization.';
  }
}
tools.push({name:'get_channel', description:'Inspect a channel or bot DM by ID, including its name, guild and recipients. Verify the destination before sending.', annotations:{readOnlyHint:true, destructiveHint:false, idempotentHint:true, openWorldHint:true}, inputSchema:{type:'object', properties:{channel_id:{type:'string'}},required:['channel_id'],additionalProperties:false}});

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const rl = readline.createInterface({input:process.stdin, crlfDelay:Infinity});
  // Keep writes in order. A mutation is never automatically retried.
  let pending = Promise.resolve();
  rl.on('line', line => { pending = pending.then(async () => {
    if (!line.trim()) return;
    let request;
    try { request = JSON.parse(line); }
    catch { writeMessage({jsonrpc:'2.0',id:null,error:{code:-32700,message:'Parse error'}}); return; }
    if (!request || typeof request !== 'object' || Array.isArray(request) || request.jsonrpc !== '2.0' || typeof request.method !== 'string') {
      writeMessage({jsonrpc:'2.0',id:null,error:{code:-32600,message:'Invalid request'}}); return;
    }
    if (!('id' in request)) return;
    try { writeMessage({jsonrpc:'2.0',id:request.id,result:await handleRequest(request)}); }
    catch(error) { writeMessage({jsonrpc:'2.0',id:request.id,error:{code:error.code || -32000,message:error.message || 'Internal error'}}); }
  }); });
}

async function handleRequest(request) {
  switch (request.method) {
    case "initialize":
      return {
        protocolVersion: request.params?.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: SERVER_INFO
      };
    case "ping":
      return {};
    case "tools/list":
      return { tools };
    case "tools/call":
      try { return await callTool(request.params || {}); }
      catch (error) {
        if (error.code === -32602) throw error;
        return {isError:true,content:[{type:'text',text:error.message || 'Tool failed.'}]};
      }
    default:
      throw jsonRpcError(-32601, `Method not found: ${request.method}`);
  }
}

export async function callTool(params) {
  const name = params.name;
  const args = params.arguments || {};

  const tool = tools.find(t=>t.name===name);
  if (!tool) throw jsonRpcError(-32602, 'Unknown tool.');
  if (!args || typeof args !== 'object' || Array.isArray(args)) throw jsonRpcError(-32602, 'Arguments must be an object.');
  for (const key of Object.keys(args)) if (!(key in tool.inputSchema.properties)) throw jsonRpcError(-32602, 'Unexpected argument.');
  for (const key of tool.inputSchema.required || []) requireString(args,key);
  for (const key of ['guild_id','channel_id','user_id']) if (key in args) snowflake(args[key]);
  for (const [key,value] of Object.entries(args)) if (tool.inputSchema.properties[key]?.type === 'string' && typeof value !== 'string') throw jsonRpcError(-32602,'Expected a string.');
  if (args.limit !== undefined && (!Number.isInteger(args.limit) || args.limit < 1 || args.limit > 100)) throw jsonRpcError(-32602,'limit must be an integer from 1 to 100.');
  switch (name) {
    case "bot_identity":
      return textResult(await client.identity());
    case "get_channel":
      return textResult(await discord('GET', '/channels/' + args.channel_id));
    case "list_guilds":
      return textResult(await discord("GET", "/users/@me/guilds"));
    case "list_channels":
      requireString(args, "guild_id");
      return textResult(await discord("GET", `/guilds/${args.guild_id}/channels`));
    case "read_messages": {
      requireString(args, "channel_id");
      const limit = clampNumber(args.limit || 20, 1, 100);
      return textResult(
        await discord("GET", `/channels/${args.channel_id}/messages?limit=${limit}`)
      );
    }
    case 'send_message':
      return textResult(await sendSafely({client, channelId:args.channel_id, content:args.content, requestId:args.request_id}));
    case "create_dm_channel":
      requireString(args, "user_id");
      return textResult(await createDmChannel(args.user_id));
    case 'send_dm': {
      if (process.env.DISCORD_ALLOW_SEND !== '1') throw Error('Sending is disabled.');
      const channel = await createDmChannel(args.user_id);
      if (channel.type !== 1 || channel.recipients?.length !== 1 || channel.recipients[0].id !== args.user_id) throw Error('DM recipient verification failed.');
      return textResult(await sendSafely({client, channelId:channel.id, content:args.content, requestId:args.request_id}));
    }
    case "read_dm_messages": {
      requireString(args, "user_id");
      const limit = clampNumber(args.limit || 20, 1, 100);
      const channel = await createDmChannel(args.user_id);
      return textResult(
        await discord("GET", `/channels/${channel.id}/messages?limit=${limit}`)
      );
    }
    case "create_text_channel":
      if (process.env.DISCORD_ALLOW_CHANNEL_CREATE !== '1') throw Error('Channel creation is disabled.');
      requireString(args, "guild_id");
      requireString(args, "name");
      return textResult(
        await discord("POST", `/guilds/${args.guild_id}/channels`, {
          name: args.name,
          topic: args.topic,
          type: 0
        })
      );
    default:
      throw jsonRpcError(-32602, `Unknown tool: ${name}`);
  }
}

async function createDmChannel(userId) {
  return discord("POST", "/users/@me/channels", {
    recipient_id: userId
  });
}

async function discord(method, path, body) {
  await client.identity();
  return client.request(method,path,body);
}

function textResult(value) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(value, null, 2)
      }
    ]
  };
}

function requireString(args, key) {
  if (typeof args[key] !== "string" || args[key].trim() === "") {
    throw jsonRpcError(-32602, `Missing or invalid string argument: ${key}`);
  }
}

function clampNumber(value, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    throw jsonRpcError(-32602, "Limit must be a number.");
  }
  return Math.max(min, Math.min(max, Math.trunc(number)));
}

function jsonRpcError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function writeMessage(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}
