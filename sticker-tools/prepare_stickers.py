#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare local AIRI sticker images and a provenance manifest; no downloads."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys

EMOTIONS = {'happy','sad','confused','surprised','thanks','celebrate','angry','tired','affectionate','awkward','agree','disagree'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(recipe, asset_root, output, dry_run=False):
    from PIL import Image
    root=Path(asset_root).resolve(strict=True)
    output=Path(output).resolve()
    pack_id=recipe.get('pack_id','')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',pack_id):
        raise ValueError('pack_id must be a safe lowercase identifier')
    if not isinstance(recipe.get('items'),list) or not 1<=len(recipe['items'])<=64:
        raise ValueError('A pack must contain 1..64 items')
    manifest={'schema_version':1,'tool_version':'0.1.0','pack_id':pack_id,
              'title':recipe.get('title',pack_id),'provenance':recipe.get('provenance',{}),
              'sources':recipe.get('sources',{}),'items':[]}
    generated=[]
    seen=set()
    for entry in recipe['items']:
        key=entry.get('id','')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',key) or key in seen:
            raise ValueError('Each item needs a unique safe lowercase id')
        seen.add(key)
        name=entry.get('name','').strip()
        emotions=entry.get('emotions',[])
        if not 1<=len(name)<=80 or not isinstance(emotions,list) or not emotions or not set(emotions)<=EMOTIONS:
            raise ValueError('Sticker metadata does not match the AIRI schema')
        relative=Path(entry['file'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Input paths must stay relative to --asset-root')
        source=(root/relative).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError('An input resolves outside --asset-root')
        original=source.read_bytes()
        with Image.open(io.BytesIO(original)) as image:
            if image.width>4096 or image.height>4096:
                raise ValueError('Source dimensions exceed 4096')
            if getattr(image,'n_frames',1)>1:
                raise ValueError('Animated input needs a separate explicit animation-preserving workflow')
            image.load()
            crop=entry.get('crop',[0,0,image.width,image.height])
            if (not isinstance(crop,list) or len(crop)!=4 or any(not isinstance(x,int) for x in crop)
                    or not (0<=crop[0]<crop[2]<=image.width and 0<=crop[1]<crop[3]<=image.height)):
                raise ValueError('Invalid source-pixel crop rectangle')
            prepared=image.crop(tuple(crop)).convert('RGBA')
            maximum=entry.get('max_side',256)
            if not isinstance(maximum,int) or not 32<=maximum<=1024:
                raise ValueError('max_side must be 32..1024')
            # Preserve aspect ratio and source pixels; no generation, inpainting,
            # background removal, or inferred parts are performed.
            factor=min(1.0,maximum/max(prepared.size))
            if factor<1:
                prepared=prepared.resize((max(1,round(prepared.width*factor)),max(1,round(prepared.height*factor))),Image.Resampling.LANCZOS)
            buffer=io.BytesIO();prepared.save(buffer,format='PNG',optimize=True)
            data=buffer.getvalue()
            if not data or len(data)>2*1024*1024:
                raise ValueError('Prepared sticker exceeds AIRI 2 MiB limit')
            filename=key+'.png'
            identity='custom-'+sha((pack_id+':'+key).encode())[:24]
            manifest['items'].append({'id':key,'airi_id':identity,'name':name,'emotions':list(dict.fromkeys(emotions)),
                'file':filename,'mime':'image/png','sha256':sha(data),'bytes':len(data),'width':prepared.width,'height':prepared.height,
                'source':{'id':entry.get('source_id'),'url':entry.get('source_url'),'nominal_seconds':entry.get('nominal_seconds'),
                          'input_sha256':sha(original),'input_file':relative.as_posix()},
                'transform':{'crop_xyxy':crop,'resize':'downscale only, Lanczos' if factor<1 else 'none',
                             'generated_pixels':False,'emotion_labels':'original descriptive interpretation, not official names'}})
            generated.append((filename,data))
    if not dry_run:
        output.mkdir(parents=True,exist_ok=True)
        for filename,data in generated:
            target=output/filename
            if target.exists() and target.read_bytes()!=data:
                raise ValueError('Output already differs; choose a new --out directory to preserve edits')
        text=json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'
        old_manifest=output/'manifest.json'
        if old_manifest.exists() and old_manifest.read_text(encoding='utf-8')!=text:
            raise ValueError('Existing manifest differs; use a new output directory')
        for filename,data in generated:
            (output/filename).write_bytes(data)
        old_manifest.write_text(text,encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe',required=True,type=Path)
    parser.add_argument('--asset-root',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:
        recipe=json.loads(args.recipe.read_text(encoding='utf-8-sig'))
        result=prepare(recipe,args.asset_root,args.out,args.dry_run)
        print(json.dumps({'ok':True,'stage':'prepare','code':'OK','count':len(result['items']),'dryRun':args.dry_run,
                          'outputs':[] if args.dry_run else [str(args.out/'manifest.json')]}))
        return 0
    except Exception as error:
        print(json.dumps({'ok':False,'stage':'prepare','code':type(error).__name__,'summary':str(error)}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
