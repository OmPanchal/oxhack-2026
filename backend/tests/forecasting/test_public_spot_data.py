from datetime import datetime,timezone
from decimal import Decimal
import numpy as np
import pytest
from app.forecasting.public_spot_data import hourly_month,parse_selected

DESIGN=dict(regionsByZoneIdPrefix={'euc1':'eu-central-1'},instanceTypes=['m5.xlarge'],product='Linux/UNIX')
HARDWARE={'m5.xlarge':dict(resourceType='CPU',gpuType=None,resourceUnitsPerInstance=4)}
START=datetime(2026,8,1,tzinfo=timezone.utc)
END=datetime(2026,9,1,tzinfo=timezone.utc)


def test_public_filter_duplicate_rejection_and_zone_identity():
    lines=[b'euc1-az2\tm5.xlarge\tLinux/UNIX\t0.4\t2026-08-01T00:00:00+00:00\n']*2
    events,report=parse_selected(lines,DESIGN,HARDWARE,start=START,end=END)
    identity=next(iter(events))
    assert identity.region=='eu-central-1' and identity.availability_zone=='euc1-az2'
    assert report['identicalDuplicates']==1
    with pytest.raises(ValueError,match='Conflicting'):
        parse_selected(lines+[lines[0].replace(b'0.4',b'0.5')],DESIGN,HARDWARE,start=START,end=END)


def test_hourly_asof_never_backfills_or_crosses_source_end():
    events={datetime(2026,8,1,0,30,tzinfo=timezone.utc):Decimal('.4'),
            datetime(2026,8,1,2,tzinfo=timezone.utc):Decimal('.8')}
    row=hourly_month(events,HARDWARE['m5.xlarge'],START,START,
                     datetime(2026,8,2,tzinfo=timezone.utc),48)
    assert np.isnan(row[0]) and row[1]==.1 and row[2]==.2 and row[23]==.2
    assert np.isnan(row[24:]).all()
    changed=dict(events);changed[datetime(2026,8,1,2,tzinfo=timezone.utc)]=Decimal('100')
    newer=hourly_month(changed,HARDWARE['m5.xlarge'],START,START,
                       datetime(2026,8,2,tzinfo=timezone.utc),48)
    np.testing.assert_array_equal(row[:2],newer[:2])


def test_invalid_values_and_product_filter():
    lines=[b'euc1-az2\tm5.xlarge\tWindows\t0.4\t2026-08-01T00:00:00+00:00\n']
    assert parse_selected(lines,DESIGN,HARDWARE,start=START,end=END)[0]=={}
    with pytest.raises(ValueError,match='Invalid'):
        parse_selected([lines[0].replace(b'Windows',b'Linux/UNIX').replace(b'0.4',b'-1')],
                       DESIGN,HARDWARE,start=START,end=END)


def test_training_examples_drop_whole_origin_when_future_label_missing():
    from app.forecasting.compare_public_regions import complete_examples
    from app.forecasting.training_data import PriceSeries
    from app.market.features import SeriesIdentity
    series=PriceSeries(SeriesIdentity('eu-central-1','euc1-az1','m5.xlarge','Linux/UNIX','CPU'),
                       {t:.1+t*.001 for t in range(240)})
    series.prices[180]=None
    x,o,h,c,a=complete_examples(series,240)
    assert np.isfinite(a).all() and (o+6<180).all()
    assert all((o==origin).sum()==6 for origin in np.unique(o))


def test_pinned_download_checksum_and_provenance_without_network(tmp_path,monkeypatch):
    from io import BytesIO
    import hashlib,json
    from app.forecasting import download_public_spot as module
    body=b'synthetic archive bytes'
    metadata=dict(access_right='open',doi='test-doi',creators=[{'name':'Test author'}],license={'id':'cc-by-4.0'})
    record=dict(id=123,metadata=metadata,files=[dict(key='2026-08.tsv.zst',size=len(body),
        checksum='md5:'+hashlib.md5(body).hexdigest())])
    def fetch(request,**kwargs):
        return BytesIO(json.dumps(record).encode() if request.full_url.endswith('/123') else body)
    monkeypatch.setattr(module.urllib.request,'urlopen',fetch)
    design=tmp_path/'design.json';design.write_text(json.dumps(dict(sourceRecord=123,sourceLicense='CC-BY-4.0',files=['2026-08.tsv.zst'])))
    receipt=module.download(design,tmp_path/'valid')
    assert receipt['files'][0]['sha256']==hashlib.sha256(body).hexdigest()
    assert (tmp_path/'valid/2026-08.tsv.zst').read_bytes()==body
    record['files'][0]['checksum']='md5:invalid'
    with pytest.raises(ValueError,match='checksum'):
        module.download(design,tmp_path/'corrupt')
    assert not (tmp_path/'corrupt/download-receipt.json').exists()
