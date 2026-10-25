"""Synthetic responses only; no AWS access or measured regional coverage."""
import json
from zipfile import ZipFile
import pytest
from app.forecasting.collect_locations import checksum, collect_locations
from test_collect_expanded import Client, CONFIG, NOW


def test_regional_archives_fixed_window_and_scratch_cleanup(tmp_path):
    scratch=tmp_path/'scratch';scratch.mkdir()
    output=tmp_path/'export'
    receipt,archive=collect_locations(lambda r:Client(r),CONFIG,output,retrieved_at=NOW,work_directory=scratch)
    assert receipt['status']=='COMPLETE' and receipt['regionsWithData']==['r1','r2']
    assert list(scratch.iterdir())==[]
    assert receipt['collectedPairCount']==4
    for r in receipt['regions']:
        path=output/r['archive']
        assert checksum(path)==r['archiveSha256']
        with ZipFile(path) as zipped:
            assert zipped.testzip() is None
            regional=json.loads(zipped.read(r['region']+'/receipt.json'))
            assert regional['startTime']=='2026-10-23T12:00:00Z'
            assert regional['endTime']==receipt['endTime']
            assert regional['hasCapacityObservations'] is False
    with ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert set(zipped.namelist())=={'export/r1.zip','export/r2.zip','export/requested-config.json','export/receipt.json'}
    with pytest.raises(ValueError,match='fresh'):
        collect_locations(lambda _:None,CONFIG,output,retrieved_at=NOW)


def test_denied_region_is_archived_and_not_mislabeled_as_coverage(tmp_path):
    receipt,archive=collect_locations(lambda r:Client(r,denied=r=='r2'),CONFIG,tmp_path/'export',retrieved_at=NOW)
    assert receipt['status']=='PARTIAL' and receipt['regionsWithData']==['r1']
    assert receipt['regions'][1]['errorCodes']=={'UnauthorizedOperation':2}
    with ZipFile(tmp_path/'export/r2.zip') as zipped:
        payload=zipped.read('r2/receipt.json')
        assert b'private SDK details' not in payload
        assert json.loads(payload)['status']=='NO_DATA'
    assert archive.is_file()


def test_no_data_still_produces_diagnostic_archive(tmp_path):
    receipt,archive=collect_locations(lambda r:Client(r,denied=True),CONFIG,tmp_path/'export',retrieved_at=NOW)
    assert receipt['status']=='NO_DATA' and receipt['regionsWithData']==[]
    assert archive.is_file()


def test_disk_failure_preserves_completed_region_zips(tmp_path,monkeypatch):
    import app.forecasting.collect_locations as module
    original=module.archive_tree
    def fail_second(directory,destination,**kwargs):
        if directory.name=='r2':
            raise OSError('Disk full')
        return original(directory,destination,**kwargs)
    monkeypatch.setattr(module,'archive_tree',fail_second)
    with pytest.raises(OSError):
        collect_locations(lambda r:Client(r),CONFIG,tmp_path/'export',retrieved_at=NOW)
    assert (tmp_path/'export/r1.zip').is_file()
    assert json.loads((tmp_path/'export/receipt.json').read_text())['status']=='FILESYSTEM_ERROR'
    assert not (tmp_path/'export.zip').exists()


def test_invalid_time_does_not_start_output(tmp_path):
    with pytest.raises(ValueError,match='hourly'):
        collect_locations(lambda _:None,CONFIG,tmp_path/'bad',end='2026-10-25T11:30:00Z',retrieved_at=NOW)
    assert not (tmp_path/'bad').exists()
