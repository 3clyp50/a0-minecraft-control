import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = path.dirname(path.dirname(request.server));
const sdk = path.join(root, '..', '@modelcontextprotocol/sdk/dist/esm/client');
const {Client} = await import(pathToFileURL(path.join(sdk, 'index.js')));
const {StdioClientTransport} = await import(pathToFileURL(path.join(sdk, 'stdio.js')));
const allowed = JSON.parse(fs.readFileSync(new URL('allowed.json', import.meta.url), 'utf8'));
const client = new Client({name: 'agent-zero-minecraft', version: '0.2.0'});
try {
    await client.connect(new StdioClientTransport({command: process.execPath, args: [request.server],
        env: {...process.env, MCPFABRIC_TOOLSETS:'info,player,vision,world,chat,session,events', MCPFABRIC_SCRIPTS:'off', MCPFABRIC_AGENT:'off'}}));
    if (request.tool === 'list') {
        const result = await client.listTools();
        console.log(JSON.stringify(result.tools.filter(tool => allowed.includes(tool.name))));
    } else {
        if (!allowed.includes(request.tool)) throw new Error('Tool is not enabled');
        console.log(JSON.stringify(await client.callTool({name: request.tool, arguments: request.params || {}})));
    }
} finally { await client.close(); }
