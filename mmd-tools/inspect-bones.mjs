// SPDX-License-Identifier: MIT
// Parse an explicitly selected local PMX with AIRI's installed real MMD parser.
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const args=Object.fromEntries(process.argv.slice(2).map(v=>{const i=v.indexOf('=');return [v.slice(0,i),v.slice(i+1)]}))
if(!args['--airi-root']||!args['--pmx']||!args['--out'])throw new Error('Use --airi-root=... --pmx=... --out=private-bones.json')
const require=createRequire(path.join(args['--airi-root'],'packages/stage-ui-mmd/package.json'))
const {MMDLoader}=await import(pathToFileURL(require.resolve('@moeru/three-mmd')).href)
globalThis.ProgressEvent??=class ProgressEvent extends Event{constructor(type,options={}){super(type);Object.assign(this,options)}}
const data=fs.readFileSync(args['--pmx'])
const server=http.createServer((_req,res)=>{res.setHeader('Content-Type','application/octet-stream');res.setHeader('Content-Length',data.length);res.end(data)})
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
let captured
const marker=new Error('PRIVATE_PMX_INSPECTION_COMPLETE')
try{
 await new MMDLoader().register(()=>({name:'inspect-bones-only',afterParse(pmx){captured={boneCount:pmx.bones.length,bones:pmx.bones.map((bone,index)=>({index,...bone}))};throw marker}})).loadAsync('http://127.0.0.1:'+server.address().port+'/model.pmx')
}catch(error){if(error!==marker)throw error}finally{server.close()}
if(!captured)throw new Error('PMX parser did not return bone metadata')
fs.writeFileSync(args['--out'],JSON.stringify(captured,null,2))
console.log(JSON.stringify({ok:true,boneCount:captured.boneCount,controlBones:captured.bones.filter(b=>/^(左腕|右腕|左ひじ|右ひじ|左手首|右手首|センター|グルーブ|上半身2?|下半身|左肩|右肩|首|頭)$/.test(b.name)).map(b=>({index:b.index,name:b.name,englishName:b.englishName,position:b.position,parentBoneIndex:b.parentBoneIndex,flag:b.flag}))},null,2))
