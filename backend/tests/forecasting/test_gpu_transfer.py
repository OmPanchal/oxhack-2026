from types import SimpleNamespace
import numpy as np
import pytest
from app.forecasting.evaluate_gpu_transfer import transfer_predictions
from app.market.features import SeriesIdentity


class Booster:
    def __init__(self):
        self.calls=[]
    def predict(self,matrix,**kwargs):
        self.calls.append(matrix.copy())
        return matrix[:,-2]*.1


def model():
    return SimpleNamespace(model=Booster(),metadata=dict(identities=[
        dict(instance_type='g5.xlarge',gpu_type='NVIDIA A10G'),
        dict(instance_type='g5.xlarge',gpu_type='NVIDIA A10G'),
        dict(instance_type='p6-b200.48xlarge',gpu_type='NVIDIA B200')],
        supportedPoolIndices=[0,1],hardware=['NVIDIA A10G','NVIDIA B200'],target='scaled',scale=2.,weight=1.))


def identity(instance='g5.xlarge',gpu='NVIDIA A10G'):
    return SeriesIdentity('us-east-1','use1-az1',instance,'Linux/UNIX','GPU',gpu)


def test_missing_pool_uses_missing_category_and_preserves_observed_features():
    m=model();features=np.arange(12,dtype=np.float32).reshape(2,6)
    current=np.array([1.,2.])
    result,fallback=transfer_predictions(m,features,current,identity(),'missing-pool-category')
    assert not fallback
    np.testing.assert_allclose(result,[.8,1.8])
    np.testing.assert_array_equal(m.model.calls[0][:,:-2],features)
    np.testing.assert_array_equal(m.model.calls[0][:,-2],[-1,-1])
    np.testing.assert_array_equal(m.model.calls[0][:,-1],[0,0])


def test_exact_instance_proxies_average_all_trained_donors_without_selection():
    m=model()
    result,fallback=transfer_predictions(m,np.zeros((2,6)),np.ones(2),identity(),
                                         'mean-exact-instance-stockholm-proxies')
    assert not fallback
    np.testing.assert_allclose(result,[1.1,1.1])
    assert [float(call[0,-2]) for call in m.model.calls]==[0.,1.]


def test_untrained_hardware_and_absent_exact_proxy_have_explicit_fallback():
    m=model();current=np.array([.3,.4])
    for mode in ('missing-pool-category','mean-exact-instance-stockholm-proxies'):
        result,fallback=transfer_predictions(m,np.zeros((2,6)),current,
            identity('p6-b200.48xlarge','NVIDIA B200'),mode)
        assert fallback
        np.testing.assert_array_equal(result,current)
    result,fallback=transfer_predictions(m,np.zeros((2,6)),current,identity('g5.2xlarge'),
        'mean-exact-instance-stockholm-proxies')
    assert fallback and not m.model.calls
    with pytest.raises(ValueError,match='Unknown'):
        transfer_predictions(m,np.zeros((2,6)),current,identity(),'select-best-using-labels')
