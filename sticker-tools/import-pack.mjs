// SPDX-License-Identifier: MIT
// Run in the AIRI renderer's MAIN world with its real Pinia stickers store.
export const emotions = new Set(['happy','sad','confused','surprised','thanks','celebrate','angry','tired','affectionate','awkward','agree','disagree'])

async function hashBytes(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('')
}

export async function importStickerPack({store,manifest,loadBytes,enabled=true,frequency=50}) {
  if(!store || typeof store.save!=='function' || typeof store.load!=='function') throw new Error('Pass the real AIRI stickers Pinia store')
  if(manifest?.schema_version!==1 || !Array.isArray(manifest.items) || !manifest.items.length || manifest.items.length>64) throw new Error('Unsupported sticker manifest')
  if(![25,50,75,100].includes(frequency)) throw new Error('Frequency must be 25, 50, 75, or 100')
  if(typeof loadBytes!=='function') throw new Error('Provide a trusted local image loader')
  await store.load()
  const prepared=[]
  const seen=new Set()
  for(const item of manifest.items) {
    if(!/^custom-[a-f0-9]{24}$/.test(item.airi_id) || !/^[a-z0-9][a-z0-9_-]{0,63}\.png$/.test(item.file)) throw new Error('Unsafe sticker identity or file path')
    if(seen.has(item.airi_id)) throw new Error('Duplicate sticker identity')
    seen.add(item.airi_id)
    if(typeof item.name!=='string' || !item.name.trim() || item.name.trim().length>80 || !Array.isArray(item.emotions) || !item.emotions.length || item.emotions.some(e=>!emotions.has(e))) throw new Error('Invalid sticker metadata')
    const bytes=new Uint8Array(await loadBytes(item.file,item))
    if(!bytes.byteLength || bytes.byteLength>2097152 || bytes.byteLength!==item.bytes || await hashBytes(bytes)!==item.sha256) throw new Error('Sticker content verification failed: '+item.id)
    const existing=store.entries.find(entry=>entry.id===item.airi_id)
    if(existing) {
      const src=store.artwork[existing.assetId]
      const existingBytes=src?await(await fetch(src)).arrayBuffer():null
      if(!existingBytes || await hashBytes(existingBytes)!==item.sha256 || existing.name!==item.name || JSON.stringify(existing.emotions)!==JSON.stringify(item.emotions)) throw new Error('Existing sticker differs; preserving user edits: '+item.id)
      prepared.push({item,skip:true})
    } else {
      prepared.push({item,file:new File([bytes],item.file,{type:'image/png'}),skip:false})
    }
  }
  // Validate all hashes/metadata before the first mutation. The real store then
  // performs its own image decode, limits, Web Lock, persistence, and broadcast.
  const results=[]
  for(const entry of prepared) {
    if(!entry.skip) await store.save(entry.item.airi_id,entry.item.name,entry.item.emotions,entry.file)
    results.push({id:entry.item.airi_id,status:entry.skip?'already-present':'imported'})
  }
  store.enabled=Boolean(enabled)
  store.frequency=frequency
  await store.load()
  return {ok:true,packId:manifest.pack_id,imported:results.filter(x=>x.status==='imported').length,
          reused:results.filter(x=>x.status==='already-present').length,enabled:store.enabled,frequency:store.frequency,results}
}
