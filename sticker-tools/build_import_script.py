#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a private main-world import payload from an explicitly selected local pack."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path,help='Private output outside this public tool repository')
    parser.add_argument('--frequency',type=int,choices=[25,50,75,100],default=50)
    parser.add_argument('--store-module',help='Optional installed AIRI asset basename containing useStickersStore')
    args=parser.parse_args()
    root=args.manifest.resolve(strict=True).parent
    output=args.out.resolve()
    repository=Path(__file__).resolve().parent.parent
    if output.is_relative_to(repository):
        raise ValueError('Private payload contains image bytes and must stay outside the public repository')
    if args.store_module and not re.fullmatch(r'[A-Za-z0-9_.-]+\.js',args.store_module):
        raise ValueError('store-module must be a safe installed asset basename')
    manifest=json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    images={}
    for item in manifest['items']:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}\.png',item['file']):
            raise ValueError('Unsafe manifest image basename')
        file=(root/item['file']).resolve(strict=True)
        if not file.is_relative_to(root):
            raise ValueError('Image resolves outside selected pack')
        data=file.read_bytes()
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('Image integrity check failed')
        images[item['file']]=base64.b64encode(data).decode('ascii')
    helper=(Path(__file__).parent/'import-pack.mjs').read_text(encoding='utf-8').replace('export const ','const ').replace('export async function ','async function ')
    script='// PRIVATE LOCAL IMAGE PAYLOAD: do not publish or package this generated file.\n(async()=>{\n'+helper+'\n'
    script+='const manifest='+json.dumps(manifest,ensure_ascii=True)+';\nconst images='+json.dumps(images)+';\n'
    script+="const pinia=document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia;if(!pinia)throw new Error('AIRI Pinia is unavailable');let store=pinia._s.get('stickers');\n"
    if args.store_module:
        script+='if(!store){const mod=await import(new URL('+json.dumps('./assets/'+args.store_module)+",location.href).href);const useStore=Object.values(mod).find(value=>typeof value==='function'&&value.$id==='stickers');if(!useStore)throw new Error('Installed sticker store export not found');store=useStore(pinia);}\n"
    script+="if(!store)throw new Error('Initialize AIRI chat or the sticker settings store first');return await importStickerPack({store,manifest,frequency:"+str(args.frequency)+",enabled:true,loadBytes:async name=>Uint8Array.from(atob(images[name]),character=>character.charCodeAt(0))});\n})()\n"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(script,encoding='utf-8')
    print(json.dumps({'ok':True,'count':len(images),'payloadBytes':len(script.encode('utf-8')),'privateOutput':str(output),'appliedToApp':False}))


if __name__=='__main__':
    main()
