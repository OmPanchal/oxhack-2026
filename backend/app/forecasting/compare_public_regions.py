"""Fixed-recipe augmentation comparison; does not replace serving artifacts."""
from pathlib import Path
import hashlib
from importlib.metadata import version
import json
from statistics import fmean
import lightgbm as lgb
import numpy as np

from app.forecasting.error_model import ErrorPriceModel
from app.forecasting.error_search import causal_matrix, metrics
from app.forecasting.public_spot_data import file_sha,load_augmented
from app.forecasting.validate_error_model import block_diagnostic


def complete_examples(series,end_slot):
    x,o,h,c,a=causal_matrix(series,end_slot)
    # Retain a whole six-horizon origin only if all its targets are known.
    mask=np.repeat(np.isfinite(a.reshape(-1,6)).all(axis=1),6)
    return x[mask],o[mask],h[mask],c[mask],a[mask]


def report_cohort(a,c,old,new,o,h,p,identities,old_supported,new_supported):
    result=dict(sampleCount=len(a),persistence=metrics(a,c,c),previousBest=metrics(a,old,c),
                augmented=metrics(a,new,c))
    result['augmented']['maeReductionVsPreviousBestPct']=(100*(1-result['augmented']['mae']/result['previousBest']['mae'])
                                                       if result['previousBest']['mae'] else None)
    base_rmse=float(np.sqrt(np.mean((a-c)**2)))
    for key in ('persistence','previousBest','augmented'):
        result[key]['rmseReductionVsPersistencePct']=100*(1-result[key]['rmse']/base_rmse) if base_rmse else None
    result['previousBestFallbackSampleCount']=int((~np.isin(p,old_supported)).sum())
    result['augmentedFallbackSampleCount']=int((~np.isin(p,new_supported)).sum())
    result['byHorizon']={str(k):dict(previousBest=metrics(a[h==k],old[h==k],c[h==k]),
        augmented=metrics(a[h==k],new[h==k],c[h==k])) for k in range(1,7)}
    pools=[]
    for idx in np.unique(p):
        mask=p==idx
        pools.append(dict(identity=identities[int(idx)],previousBest=metrics(a[mask],old[mask],c[mask]),
                          augmented=metrics(a[mask],new[mask],c[mask])))
    result['byPool']=pools
    result['poolSummary']=dict(count=len(pools),
        improvedVsPersistence=sum(r['augmented']['mae']<r['augmented']['persistenceMae'] for r in pools),
        worsenedVsPersistence=sum(r['augmented']['mae']>r['augmented']['persistenceMae'] for r in pools),
        improvedVsPreviousBest=sum(r['augmented']['mae']<r['previousBest']['mae'] for r in pools),
        worsenedVsPreviousBest=sum(r['augmented']['mae']>r['previousBest']['mae'] for r in pools))
    result['byRegion']={region:dict(previousBest=metrics(a[np.array([identities[int(i)]['region']==region for i in p])],
        old[np.array([identities[int(i)]['region']==region for i in p])],c[np.array([identities[int(i)]['region']==region for i in p])]),
        augmented=metrics(a[np.array([identities[int(i)]['region']==region for i in p])],
        new[np.array([identities[int(i)]['region']==region for i in p])],c[np.array([identities[int(i)]['region']==region for i in p])]))
        for region in sorted({identities[int(i)]['region'] for i in p})}
    result['timeBlockDiagnosticVsPreviousBest']=block_diagnostic(o,a,new,old,48)
    return result


def run(original,public,previous_models,output,models_output,design_path):
    if output.exists() or models_output.exists():
        raise ValueError('Use new report and model directories')
    design=json.loads(design_path.read_text())
    dataset,public_manifest=load_augmented(original,public)
    output.mkdir(parents=True,exist_ok=False);models_output.mkdir(parents=True,exist_ok=False)
    (output/'design.json').write_bytes(design_path.read_bytes())
    report=dict(schemaVersion='public-region-augmentation-results-v1',design=design,
        designSha256=file_sha(design_path),mergedDatasetSha256=dataset.sha256,
        originalDatasetSha256=public_manifest['originalDatasetSha256'],publicManifestSha256=file_sha(public/'manifest.json'),
        publicSeriesCount=len(public_manifest['series']),originalSeriesCount=len(dataset.series)-len(public_manifest['series']),
        publicKnownHourlyRows=public_manifest['knownHourlyRowCount'],resources={},
        packageVersions={name:version(name) for name in ('lightgbm','numpy','scikit-learn')},
        implementationSha256={name:file_sha(Path(__file__).with_name(name)) for name in
            ('compare_public_regions.py','public_spot_data.py','error_search.py','error_model.py')},
        limitations=['Fixed-recipe post-holdout development; original October periods were previously examined.',
            'New-region September results compare against incumbent persistence fallback, not incumbent trained regional models.',
            'No public October observations: new-region September and Stockholm October errors cannot be pooled as equivalent tests.',
            'No observed capacity/interruption labels, calibrated intervals, scheduler savings or serving-model replacement.'])
    for resource in ('CPU','GPU'):
        previous=ErrorPriceModel(previous_models,resource)
        pools=[s for s in dataset.series if s.identity.resource_type==resource]
        identities=[s.identity.to_dict() for s in pools]
        old_count=len(previous.metadata['identities'])
        assert identities[:old_count]==previous.metadata['identities']
        hardware=sorted({s.identity.gpu_type or s.identity.instance_type.split('.')[0] for s in pools})
        assert hardware==previous.metadata['hardware']
        matrices=[];origins=[];horizons=[];currents=[];actuals=[];ids=[]
        for idx,s in enumerate(pools):
            x,o,h,c,a=complete_examples(s,dataset.end_slot)
            hw=hardware.index(s.identity.gpu_type or s.identity.instance_type.split('.')[0])
            matrices.append(np.column_stack([x,np.full(len(x),idx),np.full(len(x),hw)]).astype(np.float32))
            origins.append(o);horizons.append(h);currents.append(c);actuals.append(a);ids.append(np.full(len(x),idx))
        x=np.concatenate(matrices);o=np.concatenate(origins);h=np.concatenate(horizons)
        c=np.concatenate(currents);a=np.concatenate(actuals);p=np.concatenate(ids)
        del matrices
        train=o+6<design['trainingEndExclusive']
        assert np.isfinite(a[train]).all()
        scale=float(np.median(c[train]));supported=np.unique(p[train])
        params=dict(design['parameters']);rounds=params.pop('num_boost_round')
        params.update(verbosity=-1,num_threads=1,seed=design['seed'],deterministic=True,force_col_wise=True)
        print(resource,'FITTING',int(train.sum()),'examples,',len(supported),'trained pools',flush=True)
        model=lgb.train(params,lgb.Dataset(x[train],label=(a[train]-c[train])/scale,
            categorical_feature=[x.shape[1]-2,x.shape[1]-1]),num_boost_round=rounds)
        model_path=models_output/f'{resource}-scaled-l1-31.txt';model.save_model(str(model_path))
        metadata=dict(schemaVersion='relative-price-error-model-v1',status='EXPERIMENTAL_PUBLIC_REGION_AUGMENTATION',
            originUtc=dataset.origin.isoformat(),datasetSha256=dataset.sha256,trainingEndExclusive=design['trainingEndExclusive'],
            modelFile=model_path.name,modelSha256=file_sha(model_path),identities=identities,
            supportedPoolIndices=supported.tolist(),hardware=hardware,target='scaled',weight=1.,scale=scale,
            featureSchema='relative-price-error-features-v1',featureImplementationSha256=file_sha(Path(__file__).with_name('error_search.py')))
        (models_output/f'{resource}-model.json').write_text(json.dumps(metadata,indent=2)+'\n')
        resource_report=dict(trainingSampleCount=int(train.sum()),trainingMaxTargetSlot=int((o[train]+h[train]).max()),
            originalTrainingSampleCount=int((train&(p<old_count)).sum()),publicTrainingSampleCount=int((train&(p>=old_count)).sum()),
            modelSha256=metadata['modelSha256'],periods={})
        for name,(start,end) in design['evaluation'].items():
            original_cohort=name.startswith('stockholm')
            score=(o>=start)&(o+6<end)&((p<old_count) if original_cohort else (p>=old_count))
            assert (o[train]+h[train]).max()<o[score].min()
            current=c[score];actual=a[score];pool=p[score]
            old_supported=np.array(previous.metadata['supportedPoolIndices'])
            old=current.copy();old_mask=np.isin(pool,old_supported)
            if old_mask.any():
                delta=previous.model.predict(x[score][old_mask],num_threads=1)
                old[old_mask]=np.maximum(0,current[old_mask]+previous.metadata['weight']*previous.metadata['scale']*delta)
            delta=model.predict(x[score],num_threads=1)
            new=np.maximum(0,current+scale*delta)
            new[~np.isin(pool,supported)]=current[~np.isin(pool,supported)]
            rows=report_cohort(actual,current,old,new,o[score],h[score],pool,identities,old_supported,supported)
            resource_report['periods'][name]=rows
            np.savez_compressed(output/f'{resource}-{name}-predictions.npz',origin=o[score],horizon=h[score],pool=pool,
                                actual=actual,persistence=current,previousBest=old,augmented=new)
            print(resource,name,'vs persistence',rows['augmented']['maeImprovementPct'],
                'vs previous',rows['augmented']['maeReductionVsPreviousBestPct'],flush=True)
        report['resources'][resource]=resource_report
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        del x,o,h,c,a,p,train,model,previous
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('original','public','previous-models','output','models-output','design'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    run(args.original,args.public,args.previous_models,args.output,args.models_output,args.design)
