"""Frozen Stockholm GPU weights on unseen regional pools; offline diagnostic only."""
from pathlib import Path
import json
import numpy as np
from app.forecasting.compare_public_regions import complete_examples
from app.forecasting.error_model import ErrorPriceModel
from app.forecasting.error_search import metrics
from app.forecasting.public_spot_data import file_sha,load_augmented
from app.forecasting.validate_error_model import block_diagnostic


def transfer_predictions(model, features, current, identity, method):
    """Never fit or adapt scaling; change only the categorical pool input."""
    if method not in {'missing-pool-category','mean-exact-instance-stockholm-proxies'}:
        raise ValueError('Unknown frozen transfer method')
    trained=[model.metadata['identities'][i] for i in model.metadata['supportedPoolIndices']]
    if identity.resource_type!='GPU':
        raise ValueError('This diagnostic is GPU only')
    hardware={row['gpu_type'] for row in trained}
    if identity.gpu_type not in hardware:
        return current.copy(),True
    hw=model.metadata['hardware'].index(identity.gpu_type)
    if method=='missing-pool-category':
        donors=[-1]
    else:
        donors=[i for i in model.metadata['supportedPoolIndices']
                if model.metadata['identities'][i]['instance_type']==identity.instance_type and
                model.metadata['identities'][i]['gpu_type']==identity.gpu_type]
        if not donors:
            return current.copy(),True
    deltas=[]
    for pool in donors:
        matrix=np.column_stack([features,np.full(len(features),pool),np.full(len(features),hw)]).astype(np.float32)
        deltas.append(model.model.predict(matrix,num_threads=1))
    delta=np.mean(deltas,axis=0)
    divisor=current if model.metadata['target']=='relative' else model.metadata['scale']
    values=current+model.metadata['weight']*divisor*delta
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite transfer predictions')
    return np.maximum(0,values),False


def summary(actual,current,prediction):
    result=metrics(actual,prediction,current)
    base_rmse=float(np.sqrt(np.mean((actual-current)**2)))
    result['rmseImprovementPct']=100*(1-result['rmse']/base_rmse) if base_rmse else None
    return result


def run(original,public,previous_models,multi_models,reference_run,output,design_path):
    if output.exists():
        raise ValueError('Use a fresh transfer output directory')
    design=json.loads(design_path.read_text())
    old=ErrorPriceModel(previous_models,'GPU');multi=ErrorPriceModel(multi_models,'GPU')
    if (old.metadata['modelSha256']!=design['oldModelSha256'] or
        multi.metadata['modelSha256']!=design['multiRegionModelSha256'] or
        file_sha(public/'manifest.json')!=design['publicManifestSha256']):
        raise ValueError('Frozen inputs differ')
    dataset,manifest=load_augmented(original,public)
    if dataset.sha256!=multi.metadata['datasetSha256']:
        raise ValueError('Augmented dataset differs from trained model')
    pools=[s for s in dataset.series if s.identity.resource_type=='GPU']
    assert [s.identity.to_dict() for s in pools]==multi.metadata['identities']
    output.mkdir(parents=True,exist_ok=False)
    (output/'design.json').write_bytes(design_path.read_bytes())
    blocks=[];predictions={name:[] for name in design['methods']};fallbacks={name:0 for name in design['methods']}
    for index,series in enumerate(pools):
        if series.identity.region=='eu-north-1':
            continue
        x,o,h,c,a=complete_examples(series,design['endSlotExclusive'])
        mask=(o>=design['startSlot'])&(o+6<design['endSlotExclusive'])
        x,o,h,c,a=x[mask],o[mask],h[mask],c[mask],a[mask]
        if not len(a):
            continue
        blocks.append(dict(origin=o,horizon=h,pool=np.full(len(o),index),actual=a,persistence=c))
        predictions['persistence'].append(c)
        for method in (design['primaryMethod'],design['secondaryMethod']):
            pred,fallback=transfer_predictions(old,x,c,series.identity,method)
            predictions[method].append(pred)
            fallbacks[method]+=len(c) if fallback else 0
        hw=multi.metadata['hardware'].index(series.identity.gpu_type)
        matrix=np.column_stack([x,np.full(len(x),index),np.full(len(x),hw)]).astype(np.float32)
        if index not in multi.metadata['supportedPoolIndices']:
            pred=c.copy();fallbacks['multi-region-trained']+=len(c)
        else:
            pred=np.maximum(0,c+multi.metadata['scale']*multi.model.predict(matrix,num_threads=1))
        predictions['multi-region-trained'].append(pred)
    arrays={key:np.concatenate([b[key] for b in blocks]) for key in blocks[0]}
    predictions={key:np.concatenate(values) for key,values in predictions.items()}
    reference=np.load(reference_run/'GPU-newRegionHistorical-predictions.npz')
    for key in arrays:
        np.testing.assert_array_equal(arrays[key],reference[key])
    np.testing.assert_array_equal(predictions['multi-region-trained'],reference['augmented'])
    actual,current=arrays['actual'],arrays['persistence']
    report=dict(schemaVersion='gpu-transfer-results-v1',design=design,designSha256=file_sha(design_path),
        datasetSha256=dataset.sha256,sampleCount=len(actual),methods={},
        implementationSha256={name:file_sha(Path(__file__).with_name(name)) for name in
            ('evaluate_gpu_transfer.py','error_search.py','error_model.py','public_spot_data.py')})
    for method,pred in predictions.items():
        rows=[]
        for index in np.unique(arrays['pool']):
            mask=arrays['pool']==index
            rows.append(dict(identity=pools[int(index)].identity.to_dict(),**summary(actual[mask],current[mask],pred[mask])))
        result=summary(actual,current,pred)
        result.update(fallbackSampleCount=fallbacks[method],byPool=rows,
            poolSummary=dict(improved=sum(r['mae']<r['persistenceMae'] for r in rows),
                worsened=sum(r['mae']>r['persistenceMae'] for r in rows),tied=sum(r['mae']==r['persistenceMae'] for r in rows)),
            byHorizon={str(h):summary(actual[arrays['horizon']==h],current[arrays['horizon']==h],pred[arrays['horizon']==h]) for h in range(1,7)},
            byRegion={},byGpuType={},timeBlockDiagnostic=block_diagnostic(arrays['origin'],actual,pred,current,48))
        for field,output_key in [('region','byRegion'),('gpu_type','byGpuType')]:
            keys=np.array([getattr(pools[int(i)].identity,field) for i in arrays['pool']])
            for key in sorted(set(keys)):
                mask=keys==key
                result[output_key][key]=summary(actual[mask],current[mask],pred[mask])
        report['methods'][method]=result
        print(method,'MAE',result['mae'],'improvement',result['maeImprovementPct'],'pools',result['poolSummary'],flush=True)
    np.savez_compressed(output/'predictions.npz',**arrays,**{k.replace('-','_'):v for k,v in predictions.items() if k!='persistence'})
    report['predictionsSha256']=file_sha(output/'predictions.npz')
    report['referencePredictionParity']=True
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('original','public','previous-models','multi-models','reference-run','output','design'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    run(args.original,args.public,args.previous_models,args.multi_models,args.reference_run,args.output,args.design)
