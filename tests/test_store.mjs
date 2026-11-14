import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../webui/store.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace('export const store =', 'globalThis.store =');
const context = vm.createContext({createStore: (_, value) => value});
vm.runInContext(source, context);
const store = context.store;
assert.equal(store.items().length, 0);
store.state.inventory = {
    hotbar: [{slot: 0, id: 'minecraft:stone', count: 1}],
    main: [{slot: 9, id: 'minecraft:dirt', count: 4}],
    armor: [{slot: 36, id: 'minecraft:iron_boots', count: 1}],
    offhand: {slot: 40, id: 'minecraft:torch', count: 16},
};
assert.equal(store.items().map(item => item.slot).join(','), '0,9,36,40');
store.state.inventory = {hotbar: [{empty: true}], offhand: {empty: true}};
assert.equal(store.items().length, 0);
console.log('Inventory display checks passed');
