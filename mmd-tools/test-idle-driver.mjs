// SPDX-License-Identifier: MIT
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {webcrypto} from 'node:crypto'

const bytes=fs.readFileSync(new URL('./examples/natural-idle.vmd',import.meta.url))
const source=fs.readFileSync(new URL('./mmd-idle-driver.js',import.meta.url),'utf8')
let imported=0
const store={availableMotions:[],idleMotionName:'previous-idle',physicsEnabled:true,unrelated:'keep',async addMotion(file){
  imported++;assert.match(file.name,/^airi-natural-idle-[a-f0-9]{12}\.vmd$/)
  this.availableMotions.push({name:file.name.slice(0,-4),id:'test-motion'})
}}
const context=vm.createContext({Uint8Array,TextDecoder,File,crypto:webcrypto,setTimeout,document:{querySelector(){return null}}})
vm.runInContext(source,context)
const install=context.installAiriMmdIdle
const first=await install({store,bytes})
assert.equal(first.ok,true);assert.equal(first.reused,false);assert.equal(first.previous.idleMotionName,'previous-idle')
assert.equal(store.physicsEnabled,false);assert.equal(store.idleMotionName,first.name);assert.equal(store.unrelated,'keep')
const again=await install({store,bytes})
assert.equal(again.reused,true);assert.equal(imported,1)
await assert.rejects(()=>install({store,bytes:new Uint8Array(80)}),/VMD 0002/)
await assert.rejects(()=>install({bytes,timeoutMs:1}),/unavailable/)
let attempts=0
context.document.querySelector=()=>++attempts<2?null:({__vue_app__:{config:{globalProperties:{$pinia:{_s:new Map([['mmd',store]])}}}}})
assert.equal((await install({bytes})).reused,true)
assert.equal(attempts,2)
console.log(JSON.stringify({ok:true,tests:5,checks:['native-store-install','content-hash-idempotence','invalid-vmd-rejected','missing-store-timeout','late-pinia-resolution']}))
