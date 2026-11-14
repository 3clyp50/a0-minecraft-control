import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../webui/config-store.js',import.meta.url),'utf8')
    .replace(/^import .*;\r?\n/gm,'').replace('export const store =','globalThis.store =');
const context=vm.createContext({createStore:(_,v)=>v,callJsonApi:async()=>({presets:['Default','Efficiency']}),
    toastFrontendError:message=>{throw new Error(message);}});
vm.runInContext(source,context);
const config={model_preset:'Efficiency',auto_resume:false};
await context.store.load(config);
assert.equal(config.model_preset,'Efficiency');
assert.equal(config.auto_resume,false);
assert.equal(config.verify_screenshot,true);
assert.equal(config.chat_relay,true);
assert.equal(context.store.ready,true);
console.log('Settings defaults preserve existing choices');
