import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../webui/store.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace('export const store =','globalThis.store =');
const calls=[],toasts=[];let timers=0;
const setup={profiles:{versions:['26.3','26.2'],recommended:'26.3',installed:[]}};
const state={online:false,launcher:{ready:true}};
const context=vm.createContext({createStore:(_,v)=>v,window:{},setInterval:()=>++timers,clearInterval:()=>{},toastFrontendError:m=>{throw new Error(m)},toastFrontendSuccess:m=>toasts.push(m),callJsonApi:async (_,data)=>{
 calls.push(data);
 if(data.action==='status')return {...state};
 if(data.action==='profile_versions'){state.setup=setup;return {setup};}
 if(data.action==='install_profile'){setup.profiles.installed=[{game_version:data.version,name:'Agent Zero '+data.version}];return {setup};}
}});
vm.runInContext(source,context);const store=context.store;
await Promise.all([store.onOpen(),store.onOpen()]);
assert.equal(timers,1);assert.equal(calls.filter(v=>v.action==='profile_versions').length,1);assert.equal(store.version,'26.3');
store.version='26.2';await store.send('install_profile');
assert.equal(calls.find(v=>v.action==='install_profile').version,'26.2');assert.equal(store.profile().name,'Agent Zero 26.2');assert.equal(toasts.length,1);assert.equal(store.sending,false);
store.cleanup();assert.equal(store.timer,null);
console.log('Profile setup and installation UI checks passed');
