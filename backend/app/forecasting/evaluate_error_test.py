"""Evaluate saved error-focused models without fitting or selecting parameters."""
from pathlib import Path
import hashlib
import json
import numpy as np
from app.forecasting.error_model import ErrorPriceModel
from app.forecasting.error_search import causal_matrix, metrics
from app.forecasting.training_data import load_prepared_dataset
from app.forecasting.contracts import slot_for_timestamp


def evaluate(dataset_path, model_path, output):
    output.mkdir(parents=True, exist_ok=False)
    root=Path(__file__).resolve().parents[3]
    original=json.loads((root/'data/final-evaluation-design.json').read_text())
    receipt=json.loads((root/'data/error-model-artifacts.json').read_text())
    for item in receipt['files']:
        file=model_path/Path(item['path']).name
        if hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Saved artifact differs from frozen receipt')
    dataset=load_prepared_dataset(dataset_path)
    if dataset.sha256!=original['datasetSha256']:
        raise ValueError('Dataset fingerprint mismatch')
    start=slot_for_timestamp(dataset.origin,original['testStartUtc'])
    end=slot_for_timestamp(dataset.origin,original['testEndUtcExclusive'])
    design=dict(status='SAVED_WEIGHTS_NO_REFIT',datasetSha256=dataset.sha256,
        originUtc=dataset.origin.isoformat(),periods=dict(designatedTest=[start,end],
        forwardDay=[end,dataset.end_slot]),originalTestAlreadyEvaluated=True,
        forwardDayStatus='PREVIOUSLY_UNSCORED_DATE_EXTENSION_SMALL_SAMPLE',
        artifactReceipt=receipt,
        implementationSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'design.json').write_text(json.dumps(design,indent=2)+'\n')
    report=dict(design=design,resources={})
    for resource in ('CPU','GPU'):
        model=ErrorPriceModel(model_path,resource)
        meta=model.metadata
        if meta['datasetSha256']!=dataset.sha256 or meta['originUtc']!=dataset.origin.isoformat() or meta['trainingEndExclusive']>=start:
            raise ValueError('Model provenance or chronology mismatch')
        collected={name:dict(origin=[],horizon=[],pool=[],actual=[],persistence=[],prediction=[],fallback=[])
                   for name in design['periods']}
        for series in [s for s in dataset.series if s.identity.resource_type==resource]:
            pool=meta['identities'].index(series.identity.to_dict())
            hardware=meta['hardware'].index(series.identity.gpu_type or series.identity.instance_type.split('.')[0])
            for name,(a,b) in design['periods'].items():
                x,o,h,c,y=causal_matrix(series,b)
                mask=(o>=a)&(o+6<b)
                x,o,h,c,y=x[mask],o[mask],h[mask],c[mask],y[mask]
                if not len(o):
                    continue
                if not np.isfinite(y).all():
                    raise ValueError('Missing evaluation labels')
                fallback=pool not in meta['supportedPoolIndices']
                if fallback:
                    pred=c.copy()
                else:
                    matrix=np.column_stack([x,np.full(len(x),pool),np.full(len(x),hardware)]).astype(np.float32)
                    delta=model.model.predict(matrix,num_threads=1)
                    divisor=c if meta['target']=='relative' else meta['scale']
                    pred=np.maximum(0,c+meta['weight']*delta*divisor)
                if not np.isfinite(pred).all():
                    raise ValueError('Nonfinite predictions')
                for field,values in dict(origin=o,horizon=h,pool=np.full(len(o),pool),actual=y,
                    persistence=c,prediction=pred,fallback=np.full(len(o),fallback)).items():
                    collected[name][field].append(values)
        report['resources'][resource]={}
        for name,parts in collected.items():
            arrays={k:np.concatenate(v) for k,v in parts.items()}
            summary=metrics(arrays['actual'],arrays['prediction'],arrays['persistence'])
            summary['persistenceRmse']=float(np.sqrt(np.mean((arrays['actual']-arrays['persistence'])**2)))
            summary['rmseImprovementPct']=100*(1-summary['rmse']/summary['persistenceRmse'])
            summary['fallbackSampleCount']=int(arrays['fallback'].sum())
            summary['byHorizon']={str(h):metrics(arrays['actual'][arrays['horizon']==h],
                arrays['prediction'][arrays['horizon']==h],arrays['persistence'][arrays['horizon']==h]) for h in range(1,7)}
            pool_metrics=[metrics(arrays['actual'][arrays['pool']==p],arrays['prediction'][arrays['pool']==p],
                                 arrays['persistence'][arrays['pool']==p]) for p in np.unique(arrays['pool'])]
            summary['poolSummary']=dict(improved=sum(p['mae']<p['persistenceMae'] for p in pool_metrics),
                worsened=sum(p['mae']>p['persistenceMae'] for p in pool_metrics),
                tied=sum(p['mae']==p['persistenceMae'] for p in pool_metrics))
            np.savez_compressed(output/f'{resource}-{name}-predictions.npz',**arrays)
            summary['predictionsSha256']=hashlib.sha256((output/f'{resource}-{name}-predictions.npz').read_bytes()).hexdigest()
            report['resources'][resource][name]=summary
            print(resource,name,summary,flush=True)
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--models',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    evaluate(args.dataset,args.models,args.output)
