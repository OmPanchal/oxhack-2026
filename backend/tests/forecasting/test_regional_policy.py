import numpy as np
import pytest
from app.forecasting.regional_policy_experiment import blend,choose_weights,reference_choices,route_predictions,select_policy,predict

DESIGN=dict(families=['persistence','pooled','regional'],weights=[0.,.25,.5,.75,1.],
            selectionCandidates=['reference','reference-blend','validation-route-blend'])


def test_blend_endpoints_and_validation_weights():
    h=np.tile(np.arange(1,7),2)
    current=np.zeros(12);raw=np.full(12,2.);actual=np.ones(12)
    weights=choose_weights(actual,current,raw,h,DESIGN['weights'])
    assert weights=={str(k):.5 for k in range(1,7)}
    np.testing.assert_array_equal(blend(current,raw,h,weights),actual)
    zero={str(k):0. for k in range(1,7)}
    np.testing.assert_array_equal(blend(current,raw,h,zero),current)
    with pytest.raises(ValueError):
        blend(current,raw,h,{str(k):2. for k in range(1,7)})


def test_reference_keeps_stockholm_gpu_specialist_and_regions_separate():
    region=np.array(['eu-north-1','us-east-1'])
    assert reference_choices('GPU',region)=={'eu-north-1':'regional','us-east-1':'pooled'}
    raw=dict(pooled=np.array([10.,20.]),regional=np.array([30.,40.]))
    np.testing.assert_array_equal(route_predictions(raw,region,reference_choices('GPU',region)),[30.,20.])


def test_selection_uses_fold_stability_and_conservative_ties():
    h=np.tile(np.arange(1,7),2);fold=np.repeat([0,1],6);regions=np.full(12,'us-east-1')
    current=np.zeros(12);actual=np.ones(12)
    raw=dict(persistence=current,pooled=np.full(12,2.),regional=np.full(12,3.))
    selected=select_policy(actual,current,h,regions,fold,raw,'CPU',DESIGN)
    assert selected['winner'] in selected['eligibleCandidates']
    for name in selected['eligibleCandidates']:
        assert all(v['mae']<=selected['candidates']['reference']['folds'][key]['mae']
                   for key,v in selected['candidates'][name]['folds'].items())
    tied=select_policy(actual,current,h,regions,fold,dict(persistence=current,pooled=current,regional=current),'CPU',DESIGN)
    assert tied['winner']=='reference'
    assert tied['regionalChoices']=={'us-east-1':'persistence'}
    assert all(w==0 for w in tied['referenceWeights'].values())


def test_empty_regional_cohort_never_calls_native_booster():
    class Forbidden:
        def predict(self,*args,**kwargs):
            raise AssertionError('Empty native predictions must not run')
    from types import SimpleNamespace
    model=SimpleNamespace(model=Forbidden())
    assert predict(model,{'current':np.array([1.])},np.array([False])).size==0


def test_selection_rejects_aggregate_gain_that_worsens_one_fold():
    h=np.tile(np.arange(1,7),2);fold=np.repeat([0,1],6);regions=np.full(12,'us-east-1')
    current=np.zeros(12);actual=np.ones(12)
    raw=dict(persistence=current,pooled=np.r_[np.zeros(6),np.ones(6)],
             regional=np.r_[np.ones(6),np.full(6,1.01)])
    selected=select_policy(actual,current,h,regions,fold,raw,'CPU',DESIGN)
    assert selected['candidates']['validation-route-blend']['overall']['mae']<selected['candidates']['reference']['overall']['mae']
    assert 'validation-route-blend' not in selected['eligibleCandidates']
    assert selected['winner']=='reference'
