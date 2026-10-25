#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Query a public official catalog; no login, cookies, bypass, or image downloads."""
import argparse
import json
from pathlib import Path
import urllib.request

ENDPOINT='https://bbs-api.miyoushe.com/misc/api/emoticon_set?gids=8'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',action='append',default=[])
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    with urllib.request.urlopen(ENDPOINT,timeout=20) as response:
        payload=json.load(response)
    if payload.get('retcode')!=0:
        raise RuntimeError('Official endpoint did not return success; stop rather than bypass access controls')
    sets=[pack for pack in payload['data']['list'] if '绝区零' in pack.get('name','')]
    terms=args.name or ['菲欧妮','菲歐妮','Phoenix']
    matches=[]
    for pack in sets:
        for item in pack.get('list',[]):
            text=json.dumps(item,ensure_ascii=False).casefold()
            if any(term.casefold() in text for term in terms):
                matches.append({'set_id':pack['id'],'set_name':pack['name'],'id':item['id'],'name':item['name'],'official_image_url':item.get('icon')})
    report={'ok':True,'endpoint':ENDPOINT,'sets':[{'id':pack['id'],'name':pack['name'],'count':len(pack.get('list',[]))} for pack in sets],
            'matchTerms':terms,'matches':matches,'scope':'Only this currently returned official catalog. No global absence claim. No media downloaded.'}
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
