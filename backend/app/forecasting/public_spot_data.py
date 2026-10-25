"""Import attributed public monthly price events without filling between months."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np
from app.forecasting.collect_spot import utc
from app.forecasting.training_data import PriceDataset, PriceSeries, load_prepared_dataset
from app.market.features import SeriesIdentity


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def parse_selected(lines, design, hardware, *, start, end):
    """Return exact monthly events. Conflicting duplicates fail rather than win."""
    prefixes=tuple((p+'-az').encode() for p in design['regionsByZoneIdPrefix'])
    types={t.encode() for t in design['instanceTypes']}
    events=defaultdict(dict)
    count=duplicates=outside=0
    for raw in lines:
        if not raw.startswith(prefixes):
            continue
        fields=raw.rstrip(b'\r\n').split(b'\t')
        if len(fields)!=5:
            raise ValueError('Malformed selected-region event')
        zone,instance,product,price,timestamp=fields
        if instance not in types or product!=design['product'].encode():
            continue
        zone,instance=zone.decode(),instance.decode()
        if not re.fullmatch(r'[a-z0-9]+-az[0-9]+',zone):
            raise ValueError('Expected a global availability-zone ID')
        region=design['regionsByZoneIdPrefix'][zone.split('-az')[0]]
        timestamp=utc(timestamp.decode())
        if not start<=timestamp<end:
            outside+=1
            continue
        price=Decimal(price.decode())
        if not price.is_finite() or price<0:
            raise ValueError('Invalid public source price')
        if instance not in hardware:
            raise ValueError('No verified instance hardware mapping')
        mapping=hardware[instance]
        identity=SeriesIdentity(region,zone,instance,design['product'],mapping['resourceType'],mapping['gpuType'] or '')
        previous=events[identity].get(timestamp)
        if previous is not None:
            if previous!=price:
                raise ValueError('Conflicting public price events')
            duplicates+=1
        events[identity][timestamp]=price
        count+=1
    return events,dict(selectedInputEvents=count,identicalDuplicates=duplicates,outsideMonthEventsExcluded=outside)


def hourly_month(events, mapping, origin, start, end, end_slot):
    """Backward as-of on exact hourly boundaries, only within this source month."""
    prices=np.full(end_slot,np.nan)
    ordered=sorted(events.items())
    index=0;current=None
    first=int((start-origin).total_seconds()//3600)
    last=int((end-origin).total_seconds()//3600)
    for slot in range(max(0,first),min(last,end_slot)):
        boundary=origin.timestamp()+slot*3600
        while index<len(ordered) and ordered[index][0].timestamp()<=boundary:
            current=ordered[index][1];index+=1
        if current is not None:
            prices[slot]=float(current/Decimal(mapping['resourceUnitsPerInstance']))
    return prices


def import_public(source, original, metadata_path, output, design_path):
    if output.exists():
        raise ValueError('Use a fresh import directory')
    design=json.loads(design_path.read_text())
    original_manifest=json.loads((original/'manifest.json').read_text())
    if original_manifest['sha256']!=design['originalDatasetSha256']:
        raise ValueError('Original dataset fingerprint mismatch')
    origin=utc(design['originUtc']);end_slot=int((utc(original_manifest['endUtc'])-origin).total_seconds()//3600)
    hardware={}
    for row in json.loads(metadata_path.read_text()):
        instance=row['instanceType']
        if instance in hardware and any(hardware[instance][k]!=row[k] for k in ('resourceType','gpuType','resourceUnitsPerInstance')):
            raise ValueError('Conflicting instance hardware mapping')
        hardware[instance]=row
    if set(design['instanceTypes'])-hardware.keys():
        raise ValueError('Requested hardware lacks original verified metadata')
    download=json.loads((source/'download-receipt.json').read_text())
    if download['recordId']!=design['sourceRecord']:
        raise ValueError('Public source record mismatch')
    prices={};reports=[]
    output.mkdir(parents=True,exist_ok=False)
    with gzip.open(output/'selected-events.jsonl.gz','xt') as stream:
        for name in design['files']:
            path=source/name
            receipt=next(r for r in download['files'] if r['file']==name)
            if file_sha(path)!=receipt['sha256']:
                raise ValueError('Public archive checksum mismatch')
            year,month=map(int,name[:7].split('-'))
            start=datetime(year,month,1,tzinfo=timezone.utc)
            end=datetime(year+(month==12),1 if month==12 else month+1,1,tzinfo=timezone.utc)
            with subprocess.Popen(['zstd','-dc',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
                events,report=parse_selected(process.stdout,design,hardware,start=start,end=end)
                error=process.stderr.read()
                if process.wait()!=0:
                    raise ValueError('Zstandard decoding failed: '+error.decode()[:200])
            report.update(file=name,seriesCount=len(events),sourceSha256=receipt['sha256'])
            for identity,values in sorted(events.items()):
                row=hourly_month(values,hardware[identity.instance_type],origin,start,end,end_slot)
                previous=prices.setdefault(identity,np.full(end_slot,np.nan))
                if np.any(np.isfinite(previous)&np.isfinite(row)):
                    raise ValueError('Monthly windows overlap')
                mask=np.isfinite(row);previous[mask]=row[mask]
                for timestamp,price in sorted(values.items()):
                    stream.write(json.dumps(dict(identity=identity.to_dict(),timestamp=timestamp.isoformat(),
                        priceUsdPerInstanceHour=str(price),sourceFile=name))+'\n')
            reports.append(report)
            print('IMPORTED',name,report,flush=True)
    identities=sorted(prices)
    matrix=np.stack([prices[s] for s in identities])
    np.savez_compressed(output/'hourly-prices.npz',prices=matrix)
    manifest=dict(schemaVersion='public-hourly-price-v1',originUtc=origin.isoformat(),endSlot=end_slot,
        sourceRecord=design['sourceRecord'],sourceDoi=design['sourceDoi'],sourceCreator=design['sourceCreator'],
        sourceLicense=design['sourceLicense'],sourceFiles=reports,originalDatasetSha256=design['originalDatasetSha256'],
        hardwareMetadataSha256=file_sha(metadata_path),designSha256=file_sha(design_path),dataKind='OBSERVED',
        hasCapacityObservations=False,knownHourlyRowCount=int(np.isfinite(matrix).sum()),
        missingHourlyRowCount=int(np.isnan(matrix).sum()),
        series=[dict(identity=s.to_dict(),knownHours=int(np.isfinite(prices[s]).sum()),
            hardware={k:hardware[s.instance_type][k] for k in ('resourceType','gpuType','resourceUnitsPerInstance','unit')}) for s in identities],
        sha256=file_sha(output/'hourly-prices.npz'),eventsSha256=file_sha(output/'selected-events.jsonl.gz'),
        limitations=['Third-party AWS event archive under CC-BY-4.0; monthly anchors may have source-adjusted timestamps.',
            'Global AZ IDs are preserved; no mapping to account-specific AZ letters is assumed.',
            'Verified original instance-type hardware counts are reused; no claim of current regional capacity/offerings.',
            'Hourly carry-forward assumes source completeness within a month; no fill into absent months or October.'])
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def load_augmented(original, public):
    dataset=load_prepared_dataset(original)
    manifest=json.loads((public/'manifest.json').read_text())
    if manifest['originalDatasetSha256']!=dataset.sha256 or manifest['sha256']!=file_sha(public/'hourly-prices.npz'):
        raise ValueError('Augmented dataset fingerprint mismatch')
    if utc(manifest['originUtc'])!=dataset.origin or manifest['endSlot']!=dataset.end_slot:
        raise ValueError('Dataset clocks do not match')
    matrix=np.load(public/'hourly-prices.npz',allow_pickle=False)['prices']
    if matrix.shape!=(len(manifest['series']),dataset.end_slot) or np.isinf(matrix).any() or np.any(matrix<0):
        raise ValueError('Invalid public hourly matrix')
    identities={s.identity for s in dataset.series}
    for row,values in zip(manifest['series'],matrix):
        identity=SeriesIdentity(**row['identity'])
        if identity in identities:
            raise ValueError('Original and public pool identity collision')
        identities.add(identity)
        dataset.series.append(PriceSeries(identity,{slot:float(p) if np.isfinite(p) else None for slot,p in enumerate(values)}))
    dataset.sha256=hashlib.sha256((dataset.sha256+file_sha(public/'manifest.json')).encode()).hexdigest()
    return dataset,manifest
