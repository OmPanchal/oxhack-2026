"""Download a pinned open Zenodo dataset and verify published file checksums."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request


def download(design_path, output):
    design=json.loads(Path(design_path).read_text())
    if output.exists():
        raise ValueError('Choose a fresh source directory')
    record_id=design['sourceRecord']
    if type(record_id) is not int or record_id<=0:
        raise ValueError('Invalid source record')
    request=urllib.request.Request(f'https://zenodo.org/api/records/{record_id}',
        headers={'User-Agent':'compute-arbitrage-research/1.0'})
    with urllib.request.urlopen(request,timeout=60) as stream:
        record=json.load(stream)
    if record['id']!=record_id or record['metadata']['access_right']!='open':
        raise ValueError('Expected the pinned open source record')
    if record['metadata']['license']['id'].casefold()!=design['sourceLicense'].casefold():
        raise ValueError('Public source license differs from the pinned design')
    output.mkdir(parents=True,exist_ok=False)
    (output/'source-record.json').write_text(json.dumps(record,indent=2)+'\n')
    receipts=[]
    for name in design['files']:
        if not re.fullmatch(r'\d{4}-\d{2}\.tsv\.zst',name):
            raise ValueError('Invalid monthly source filename')
        item=next(row for row in record['files'] if row['key']==name)
        url=f'https://zenodo.org/api/records/{record_id}/files/{name}/content'
        path=output/name;pending=output/(name+'.pending')
        md5=hashlib.md5();sha=hashlib.sha256();size=0
        request=urllib.request.Request(url,headers={'User-Agent':'compute-arbitrage-research/1.0'})
        with urllib.request.urlopen(request,timeout=120) as source,pending.open('xb') as target:
            while chunk:=source.read(1024*1024):
                target.write(chunk);md5.update(chunk);sha.update(chunk);size+=len(chunk)
        if size!=item['size'] or 'md5:'+md5.hexdigest()!=item['checksum']:
            raise ValueError('Downloaded archive checksum mismatch')
        pending.replace(path)
        receipts.append(dict(file=name,url=url,size=size,md5=md5.hexdigest(),sha256=sha.hexdigest()))
        print('VERIFIED',name,size,flush=True)
    receipt=dict(recordId=record_id,doi=record['metadata']['doi'],creator=record['metadata']['creators'],
                 license=record['metadata']['license'],files=receipts)
    (output/'download-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    download(args.design,args.output)
