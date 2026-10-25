from pathlib import Path
import numpy as np
from app.forecasting import error_search
from app.forecasting.error_search import causal_matrix, metrics
from app.forecasting.training_data import PriceSeries
from app.market.features import SeriesIdentity


def series():
    return PriceSeries(SeriesIdentity('r','a','c.x','Linux','CPU'),
                       {i: 1+i*.001 for i in range(240)})


def test_features_ignore_future_prices():
    s=series()
    x,o,h,c,a=causal_matrix(s,240)
    for i in range(201,240):
        s.prices[i]*=50
    xx,oo,hh,cc,aa=causal_matrix(s,240)
    np.testing.assert_array_equal(x[o<=200],xx[oo<=200])
    np.testing.assert_array_equal(c[o<=200],cc[oo<=200])
    assert np.any(a[o==200]!=aa[oo==200])


def test_targets_and_missing_history():
    s=series(); s.prices[170]=None
    x,o,h,c,a=causal_matrix(s,240)
    assert np.all(o<170)
    expected=[s.prices[int(t)] for t in o+h]
    np.testing.assert_allclose(a,np.array(expected,dtype=float),equal_nan=True)
    assert set(h)==set(range(1,7))


def test_metrics_known_values():
    result=metrics(np.array([2.,4.]),np.array([1.5,3.5]),np.array([1.,3.]))
    assert result['maeImprovementPct']==50
    assert result['mae']==.5
    assert result['rmse']==.5


def test_saved_model_inference_matches_batch_and_ignores_future(tmp_path):
    import hashlib
    import json
    import lightgbm as lgb
    from app.forecasting.error_model import ErrorPriceModel
    s=series()
    x,o,h,c,a=causal_matrix(s,240)
    xx=np.column_stack([x,np.zeros(len(x)),np.zeros(len(x))]).astype(np.float32)
    booster=lgb.train(dict(objective='regression_l1',num_threads=1,verbosity=-1,
                           min_data_in_leaf=2,num_leaves=3),
                       lgb.Dataset(xx,label=(a-c)/c),num_boost_round=3)
    path=tmp_path/'model.txt'
    booster.save_model(str(path))
    metadata=dict(schemaVersion='relative-price-error-model-v1',modelFile=path.name,
        modelSha256=hashlib.sha256(path.read_bytes()).hexdigest(),identities=[s.identity.to_dict()],
        supportedPoolIndices=[0],hardware=['c'],target='relative',weight=1.,scale=1.,
        featureImplementationSha256=hashlib.sha256(Path(error_search.__file__).read_bytes()).hexdigest())
    (tmp_path/'CPU-model.json').write_text(json.dumps(metadata))
    model=ErrorPriceModel(tmp_path,'CPU')
    mask=(o==200)&(h==3)
    expected=float(c[mask][0]*(1+booster.predict(xx[mask],num_threads=1)[0]))
    assert abs(model.predict(s.prices,s.identity,200,3)-expected)<1e-12
    for i in range(201,240):
        s.prices[i]*=100
    assert abs(model.predict(s.prices,s.identity,200,3)-expected)<1e-12
    assert model.predict({200: 2.},s.identity,200,3)==2.


def test_time_blocks_preserve_pool_and_horizon_groups():
    from app.forecasting.validate_error_model import block_diagnostic
    origins=np.repeat(np.arange(144),12)
    actual=np.full(len(origins),2.)
    result=block_diagnostic(origins,actual,np.full(len(origins),1.5),np.ones(len(origins)),24)
    assert result['blockCount']==6
    assert result['improvedBlockCount']==6
    assert result['maeReduction95PercentileInterval']==[50.,50.]
