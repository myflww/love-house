import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../../nkb/viz/web/remote-mobile.js',import.meta.url),'utf8');
const {mcpText,captureCaption}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const plain=value=>JSON.parse(JSON.stringify(value));
test('mobile exports an authenticated HTTPS MCP endpoint without local command paths',()=>{
 const mcp={mcpServers:{memory:{url:'https://memory.example/mcp/fixture',headers:{Authorization:'Bearer FAKE-MEMORY-CONNECTION'}}}};
 assert.deepEqual(JSON.parse(mcpText({mcp_config:mcp})),mcp);
 for(const url of ['http://127.0.0.1/mcp/fixture','https://'+'user'+':'+'pass'+'@memory.example/mcp/x','https://memory.example/mcp/x?token=FAKE','https://memory.example/mcp/x#secret'])assert.equal(mcpText({mcp_config:{mcpServers:{memory:{url}}}}),'');
 assert.equal(mcpText({mcp_config:{mcpServers:{memory:{command:'C:\\LoveHouse\\bridge.exe',args:[],url:'https://memory.example'}}}}),'');
});
test('mobile distinguishes generated config, tool heartbeat and an actual saved host turn',()=>{
 assert.equal(captureCaption({enabled:true,host_online:false})[0],'等待 Agent 加载配置');
 assert.equal(captureCaption({enabled:true,host_online:true,archive_status:'tools_only'})[0],'记忆工具已连接');
 assert.equal(captureCaption({enabled:true,host_online:true,archive_status:'automatic_connected',capture:{automatic_dialogues_saved:2}})[0],'已验证收到自动记录');
 assert.notEqual(captureCaption({enabled:true,host_online:true,archive_status:'automatic_connected',capture:{automatic_dialogues_saved:0}})[0],'已验证收到自动记录');
 assert.equal(captureCaption({enabled:false,host_online:true,archive_status:'automatic_connected',capture:{automatic_dialogues_saved:2}})[0],'记录已暂停');
 assert.equal(captureCaption({revoked:true})[0],'连接已断开');
});
