"""Fixed-candidate temporal stability and correlated-error diagnostics."""
from pathlib import Path
import hashlib
import json
import lightgbm as lgb
import numpy as np
from app.forecasting.error_search import causal_matrix, metrics
from app.forecasting.error_model import export_selected_model
from app.forecasting.training_data import load_prepared_dataset


def block_diagnostic(origins, actual, prediction, persistence, hours, *, seed=42):
    """Resample time blocks jointly across pools and horizons, never iid rows."""
    indices=(origins-int(origins.min()))//hours
    groups=np.unique(indices)
    losses=np.array([[np.abs(actual[indices==i]-prediction[indices==i]).sum(),
                      np.abs(actual[indices==i]-persistence[indices==i]).sum()] for i in groups])
    sample=np.random.default_rng(seed).integers(0,len(groups),size=(5000,len(groups)))
    totals=losses[sample].sum(axis=1)
    improvement=100*(1-totals[:,0]/totals[:,1])
    return dict(blockHours=hours,blockCount=len(groups),replicates=5000,
        maeReduction95PercentileInterval=np.percentile(improvement,[2.5,97.5]).tolist(),
        improvedBlockCount=int((losses[:,0]<losses[:,1]).sum()),
        tiedBlockCount=int((losses[:,0]==losses[:,1]).sum()))


def validate(dataset_path, run_path, output):
    output.mkdir(parents=True,exist_ok=False)
    source=json.loads((run_path/'report.json').read_text())
    design=dict(status='POST_SELECTION_STABILITY_DIAGNOSTIC_NOT_BLIND',
        sourceReportSha256=hashlib.sha256((run_path/'report.json').read_bytes()).hexdigest(),
        folds=[[488,744],[744,1000],[1000,1257]],
        candidates={r:source['resources'][r]['winner'] for r in ('CPU','GPU')},
        blockHours=[24,48],bootstrapReplicates=5000,
        rule='Do not reselect or tune models using these diagnostics.',
        implementationSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'design.json').write_text(json.dumps(design,indent=2)+'\n')
    dataset=load_prepared_dataset(dataset_path)
    results=dict(design=design,resources={})
    for resource in ('CPU','GPU'):
        metadata=export_selected_model(run_path,dataset,resource)
        if metadata['target']!='scaled' or metadata['weight']!=1:
            raise ValueError('Frozen validation requires selected scaled L1 model')
        pools=[s for s in dataset.series if s.identity.resource_type==resource]
        xx=[];oo=[];hh=[];cc=[];aa=[];pp=[]
        for idx,s in enumerate(pools):
            x,o,h,c,a=causal_matrix(s,1257)
            hw=metadata['hardware'].index(s.identity.gpu_type or s.identity.instance_type.split('.')[0])
            xx.append(np.column_stack([x,np.full(len(x),idx),np.full(len(x),hw)]))
            oo.append(o);hh.append(h);cc.append(c);aa.append(a);pp.append(np.full(len(x),idx))
        x=np.concatenate(xx).astype(np.float32);o=np.concatenate(oo);h=np.concatenate(hh)
        c=np.concatenate(cc);a=np.concatenate(aa);p=np.concatenate(pp)
        del xx
        folds=[]
        for start,end in design['folds']:
            train=o+6<start;score=(o>=start)&(o+6<end)
            assert (o[train]+h[train]).max()<o[score].min()
            scale=float(np.median(c[train]))
            model=lgb.train(dict(objective='regression_l1',num_leaves=31,learning_rate=.04,
                min_data_in_leaf=100,lambda_l2=1,verbosity=-1,num_threads=1,
                seed=42,deterministic=True,force_col_wise=True),
                lgb.Dataset(x[train],label=(a[train]-c[train])/scale,
                    categorical_feature=[x.shape[1]-2,x.shape[1]-1]),num_boost_round=200)
            pred=np.maximum(0,c[score]+scale*model.predict(x[score],num_threads=1))
            unsupported=~np.isin(p[score],np.unique(p[train]));pred[unsupported]=c[score][unsupported]
            row=dict(trainEndExclusive=start,scoreEndExclusive=end,trainingSampleCount=int(train.sum()),
                trainingMaxTargetSlot=int((o[train]+h[train]).max()),firstScoreOriginSlot=int(o[score].min()),
                fallbackSampleCount=int(unsupported.sum()),**metrics(a[score],pred,c[score]))
            folds.append(row)
            print(resource,'rolling',start,end,row,flush=True)
        saved=np.load(run_path/f'{resource}-winner-predictions.npz')
        origin=saved['origin'];actual=saved['actual'];pred=saved['prediction'];base=saved['persistence']
        for idx,s in enumerate(pools):
            mask=saved['pool']==idx
            np.testing.assert_array_equal(base[mask],[s.prices[int(t)] for t in origin[mask]])
            np.testing.assert_array_equal(actual[mask],[s.prices[int(t)] for t in (origin+saved['horizon'])[mask]])
        chosen=next(r for r in source['resources'][resource]['candidates'] if r['name']==source['resources'][resource]['winner'])
        np.testing.assert_allclose(metrics(actual,pred,base)['mae'],chosen['confirmation']['mae'],rtol=1e-13)
        rows=source['resources'][resource]['byPool']
        results['resources'][resource]=dict(rollingFolds=folds,confirmation=chosen['confirmation'],
            confirmationLabelAudit='ALL_MATCH_OBSERVED_SOURCE',
            byHorizon={str(i):metrics(actual[saved['horizon']==i],pred[saved['horizon']==i],base[saved['horizon']==i]) for i in range(1,7)},
            poolSummary=dict(improved=sum(r['mae']<r['persistenceMae'] for r in rows),
                worsened=sum(r['mae']>r['persistenceMae'] for r in rows),tied=sum(r['mae']==r['persistenceMae'] for r in rows)),
            blockDiagnostics=[block_diagnostic(origin,actual,pred,base,i) for i in design['blockHours']])
        (output/'report.json').write_text(json.dumps(results,indent=2)+'\n')
    return results

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    validate(args.dataset,args.run,args.output)
