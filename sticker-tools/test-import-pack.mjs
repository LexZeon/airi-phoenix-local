// SPDX-License-Identifier: MIT
import test from 'node:test'
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {importStickerPack} from './import-pack.mjs'

// Synthetic original fixture bytes; no official artwork is bundled in tests.
const bytes=new Uint8Array([80,78,71,1,2,3])
const digest=createHash('sha256').update(bytes).digest('hex')
const item={id:'sample',airi_id:'custom-'+('a'.repeat(24)),file:'sample.png',name:'Synthetic fixture',emotions:['happy'],bytes:bytes.length,sha256:digest}
const manifest={schema_version:1,pack_id:'synthetic-test',items:[item]}
function makeStore(){return {entries:[],artwork:{},enabled:false,frequency:25,writes:0,
  async load(){},async save(id,name,emotions,file){this.writes++;const assetId='image-'+this.writes;this.artwork[assetId]=URL.createObjectURL(file);this.entries.push({id,name,emotions,assetId})}}}

test('imports once and reuses verified stable identities',async()=>{
  const store=makeStore()
  const first=await importStickerPack({store,manifest,loadBytes:async()=>bytes})
  assert.equal(first.imported,1);assert.equal(store.enabled,true);assert.equal(store.frequency,50)
  const second=await importStickerPack({store,manifest,loadBytes:async()=>bytes})
  assert.equal(second.reused,1);assert.equal(store.writes,1)
})
test('refuses unsafe paths and identities before mutation',async()=>{
  for(const patch of [{file:'../sample.png'},{airi_id:'builtin-default'}]){
    const store=makeStore()
    await assert.rejects(importStickerPack({store,manifest:{...manifest,items:[{...item,...patch}]},loadBytes:async()=>bytes}))
    assert.equal(store.writes,0)
  }
})
test('preflights all hashes before the first write',async()=>{
  const store=makeStore()
  await assert.rejects(importStickerPack({store,manifest:{...manifest,items:[item,{...item,id:'second',airi_id:'custom-'+('b'.repeat(24)),sha256:'0'.repeat(64)}]},loadBytes:async()=>bytes}))
  assert.equal(store.writes,0);assert.equal(store.enabled,false)
})
test('preserves existing user metadata instead of overwriting',async()=>{
  const store=makeStore()
  await importStickerPack({store,manifest,loadBytes:async()=>bytes})
  store.entries[0].name='User edited name'
  await assert.rejects(importStickerPack({store,manifest,loadBytes:async()=>bytes}),/preserving user edits/)
  assert.equal(store.entries[0].name,'User edited name');assert.equal(store.writes,1)
})
test('rejects invalid emotion/frequency without writes',async()=>{
  const store=makeStore()
  await assert.rejects(importStickerPack({store,manifest,loadBytes:async()=>bytes,frequency:33}))
  await assert.rejects(importStickerPack({store,manifest:{...manifest,items:[{...item,emotions:['invented']}]},loadBytes:async()=>bytes}))
  assert.equal(store.writes,0)
})
