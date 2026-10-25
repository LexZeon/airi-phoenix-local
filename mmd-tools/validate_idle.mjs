// SPDX-License-Identifier: MIT
import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const args=Object.fromEntries(process.argv.slice(2).map(v=>{const i=v.indexOf('=');return [v.slice(0,i),v.slice(i+1)]}))
const require=createRequire(path.join(args['--airi-root'],'packages/stage-ui-mmd/package.json'))
const {VmdObject}=await import(pathToFileURL(require.resolve('@moeru/three-mmd')).href)
const bytes=fs.readFileSync(args['--vmd']);const data=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)
const vmd=VmdObject.ParseFromBuffer(data);const tracks=new Map();let norms=true
for(let i=0;i<vmd.boneKeyFrames.length;i++){
 const frame=vmd.boneKeyFrames.get(i);if(!tracks.has(frame.boneName))tracks.set(frame.boneName,[]);tracks.get(frame.boneName).push(frame)
 norms&&=Math.abs(Math.hypot(...frame.rotation)-1)<1e-5
}
let seamless=true
for(const frames of tracks.values()){
 frames.sort((a,b)=>a.frameNumber-b.frameNumber);const first=frames[0],last=frames.at(-1)
 seamless&&=first.frameNumber===0&&last.frameNumber===360&&[...first.position,...first.rotation].every((v,i)=>Math.abs(v-[...last.position,...last.rotation][i])<1e-6)
}
const facialBones=new Set(['頭','首','左目','右目','両目','head','Head','neck','Neck','Eyes','EyeLeft','EyeRight'])
const report={ok:norms&&seamless&&vmd.morphKeyFrames.length===0,parser:'Installed @moeru/three-mmd VmdObject',boneTracks:[...tracks.keys()],boneKeyframes:vmd.boneKeyFrames.length,morphKeyframes:vmd.morphKeyFrames.length,normalizedQuaternions:norms,seamlessLoopEndpoints:seamless,headEyeMouthTracks:[...tracks.keys()].some(name=>facialBones.has(name))}
report.ok&&=!report.headEyeMouthTracks
if(args['--out'])fs.writeFileSync(args['--out'],JSON.stringify(report,null,2))
console.log(JSON.stringify(report,null,2));if(!report.ok)process.exitCode=1
