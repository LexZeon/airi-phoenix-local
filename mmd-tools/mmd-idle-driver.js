// SPDX-License-Identifier: MIT
// MAIN-world helper. Uses AIRI's native motion store rather than replacing its render loop.
async function installAiriMmdIdle({bytes,pinia,store,moduleUrl,timeoutMs=30000}={}) {
  pinia??=globalThis.document?.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
  store??=pinia?._s.get('mmd')
  if(!store && moduleUrl){const module=await import(moduleUrl);const useStore=Object.values(module).find(value=>typeof value==='function'&&value.$id==='mmd');if(useStore)store=useStore(pinia)}
  const deadline=Date.now()+timeoutMs
  while(!store && Date.now()<deadline){
    await new Promise(resolve=>setTimeout(resolve,200))
    pinia??=globalThis.document?.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia
    store=pinia?._s.get('mmd')
  }
  if(!store || typeof store.addMotion!=='function')throw new Error('AIRI native MMD store is unavailable')
  const data=new Uint8Array(bytes)
  const signature='Vocaloid Motion Data 0002'
  if(data.byteLength<74 || new TextDecoder().decode(data.subarray(0,signature.length))!==signature)throw new Error('Supply a generated VMD 0002 motion')
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(v=>v.toString(16).padStart(2,'0')).join('')
  const name='airi-natural-idle-'+hash.slice(0,12)
  const previous={idleMotionName:store.idleMotionName,physicsEnabled:store.physicsEnabled}
  const existing=store.availableMotions.find(motion=>motion.name===name)
  if(!existing)await store.addMotion(new File([data],name+'.vmd',{type:'application/octet-stream'}))
  store.physicsEnabled=false
  store.idleMotionName=name
  // No eye/head/morph writes: the native scene retains gaze, blink, and audio lip-sync.
  return {ok:true,name,bytes:data.byteLength,sha256:hash,reused:Boolean(existing),physicsEnabled:store.physicsEnabled,
          previous,playback:'Native MMDScene asynchronously loads this stored motion and loops it.'}
}
globalThis.installAiriMmdIdle=installAiriMmdIdle
