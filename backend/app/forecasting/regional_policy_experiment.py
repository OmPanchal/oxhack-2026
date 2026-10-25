"""Bounded rolling selection of regional specialists and persistence blending."""
from pathlib import Path
from shutil import copy2
import json
from types import SimpleNamespace

import lightgbm as lgb
import numpy as np

from app.forecasting.compare_public_regions import complete_examples
from app.forecasting.error_model import ErrorPriceModel
from app.forecasting.error_search import metrics
from app.forecasting.public_spot_data import file_sha,load_augmented
from app.forecasting.validate_error_model import block_diagnostic

ROOT=Path(__file__).resolve().parents[3]


def blend(current,raw,horizons,weights):
    w=np.array([weights[str(int(h))] for h in horizons])
    if np.any(w<0) or np.any(w>1):
        raise ValueError('Blend weights must be within [0,1]')
    return current+w*(raw-current)


def choose_weights(actual,current,raw,horizons,grid):
    return {str(h):min(grid,key=lambda w:(float(np.abs(actual[horizons==h]-(current[horizons==h]+w*(raw[horizons==h]-current[horizons==h]))).mean()),w))
            for h in range(1,7)}


def route_predictions(families,regions,choices):
    result=np.empty(len(regions))
    for region in sorted(set(regions)):
        mask=regions==region
        result[mask]=families[choices[region]][mask]
    return result


def reference_choices(resource,regions):
    return {region:'regional' if resource=='GPU' and region=='eu-north-1' else 'pooled' for region in sorted(set(regions))}


def select_policy(actual,current,horizons,regions,folds,raw,resource,design):
    choices={region:min(design['families'],key=lambda family:(
        float(np.abs(actual[regions==region]-raw[family][regions==region]).mean()),design['families'].index(family)))
        for region in sorted(set(regions))}
    reference=route_predictions(raw,regions,reference_choices(resource,regions))
    routed=route_predictions(raw,regions,choices)
    reference_weights=choose_weights(actual,current,reference,horizons,design['weights'])
    route_weights=choose_weights(actual,current,routed,horizons,design['weights'])
    candidates={'reference':reference,'reference-blend':blend(current,reference,horizons,reference_weights),
                'validation-route-blend':blend(current,routed,horizons,route_weights)}
    reports={}
    for name,pred in candidates.items():
        reports[name]=dict(overall=metrics(actual,pred,current),
            folds={str(int(f)):metrics(actual[folds==f],pred[folds==f],current[folds==f]) for f in np.unique(folds)})
    eligible=[name for name in design['selectionCandidates'] if all(
        reports[name]['folds'][f]['mae']<=reports['reference']['folds'][f]['mae'] for f in reports[name]['folds'])]
    winner=min(eligible,key=lambda name:(reports[name]['overall']['mae'],design['selectionCandidates'].index(name)))
    return dict(winner=winner,eligibleCandidates=eligible,candidates=reports,
        referenceChoices=reference_choices(resource,regions),regionalChoices=choices,
        referenceWeights=reference_weights,regionalWeights=route_weights)


def build_matrix(dataset,resource):
    pools=[s for s in dataset.series if s.identity.resource_type==resource]
    identities=[s.identity.to_dict() for s in pools]
    hardware=sorted({s.identity.gpu_type or s.identity.instance_type.split('.')[0] for s in pools})
    blocks=[]
    for index,series in enumerate(pools):
        x,o,h,c,a=complete_examples(series,dataset.end_slot)
        hw=hardware.index(series.identity.gpu_type or series.identity.instance_type.split('.')[0])
        blocks.append(dict(x=np.column_stack([x,np.full(len(x),index),np.full(len(x),hw)]).astype(np.float32),
            origin=o,horizon=h,current=c,actual=a,pool=np.full(len(x),index)))
    arrays={key:np.concatenate([b[key] for b in blocks]) for key in blocks[0]}
    arrays['region']=np.array([identities[int(p)]['region'] for p in arrays['pool']])
    return arrays,identities,hardware


def fit_model(arrays,train,identities,hardware,design,directory,name):
    if not train.any():
        return None
    scale=float(np.median(arrays['current'][train]))
    params=dict(design['parameters']);rounds=params.pop('num_boost_round')
    params.update(verbosity=-1,num_threads=1,seed=design['seed'],deterministic=True,force_col_wise=True)
    model=lgb.train(params,lgb.Dataset(arrays['x'][train],label=(arrays['actual'][train]-arrays['current'][train])/scale,
        categorical_feature=[arrays['x'].shape[1]-2,arrays['x'].shape[1]-1]),num_boost_round=rounds)
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f'{name}.txt';model.save_model(str(path))
    metadata=dict(schemaVersion='relative-price-error-model-v1',originUtc=design['originUtc'],
        modelFile=path.name,modelSha256=file_sha(path),identities=identities,hardware=hardware,
        supportedPoolIndices=np.unique(arrays['pool'][train]).tolist(),scale=scale,target='scaled',weight=1.,
        trainingMaxTargetSlot=int((arrays['origin'][train]+arrays['horizon'][train]).max()),
        featureImplementationSha256=file_sha(Path(__file__).with_name('error_search.py')))
    (directory/f'{name}.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return SimpleNamespace(model=model,metadata=metadata)


def predict(model,arrays,score):
    current=arrays['current'][score]
    if model is None or not len(current):
        return current.copy()
    result=np.maximum(0,current+model.metadata['scale']*model.model.predict(arrays['x'][score],num_threads=1))
    result[~np.isin(arrays['pool'][score],model.metadata['supportedPoolIndices'])]=current[~np.isin(arrays['pool'][score],model.metadata['supportedPoolIndices'])]
    if not np.isfinite(result).all():
        raise ValueError('Nonfinite policy predictions')
    return result


def load_inputs(original,public,design_path):
    design=json.loads(design_path.read_text())
    for name,sha in design['frozenInputs'].items():
        if file_sha(ROOT/name)!=sha:
            raise ValueError('Frozen policy input changed: '+name)
    dataset,_=load_augmented(original,public)
    return design,dataset


def run_selection(original,public,output,design_path):
    if output.exists():
        raise ValueError('Use a fresh selection directory')
    design,dataset=load_inputs(original,public,design_path)
    output.mkdir(parents=True,exist_ok=False)
    copy2(design_path,output/'design.json')
    for resource in ('CPU','GPU'):
        arrays,identities,hardware=build_matrix(dataset,resource)
        collected=[];raw={family:[] for family in design['families']}
        for fold,(start,end) in enumerate(design['folds']):
            train=arrays['origin']+6<start
            score=(arrays['origin']>=start)&(arrays['origin']+6<end)
            assert (arrays['origin'][train]+arrays['horizon'][train]).max()<arrays['origin'][score].min()
            print(resource,'ROLLING',start,end,'pooled',int(train.sum()),flush=True)
            pooled=fit_model(arrays,train,identities,hardware,design,output/'rolling-models',f'{resource}-{start}-pooled')
            pooled_pred=predict(pooled,arrays,score)
            regional_pred=arrays['current'][score].copy()
            for region in sorted(set(arrays['region'])):
                mask=score&(arrays['region']==region)
                model=fit_model(arrays,train&(arrays['region']==region),identities,hardware,design,
                    output/'rolling-models',f'{resource}-{start}-{region}')
                regional_pred[arrays['region'][score]==region]=predict(model,arrays,mask)
                print(resource,'ROLLING',start,region,'complete',flush=True)
            collected.append({**{key:arrays[key][score] for key in ('origin','horizon','current','actual','pool','region')},
                              'fold':np.full(int(score.sum()),fold)})
            raw['persistence'].append(arrays['current'][score]);raw['pooled'].append(pooled_pred);raw['regional'].append(regional_pred)
        data={key:np.concatenate([b[key] for b in collected]) for key in collected[0]}
        raw={key:np.concatenate(value) for key,value in raw.items()}
        selection=select_policy(data['actual'],data['current'],data['horizon'],data['region'],data['fold'],raw,resource,design)
        selection.update(resource=resource,selectionMaxTargetSlot=int((data['origin']+data['horizon']).max()),
            firstFoldTrainingMaxTargetSlot=design['folds'][0][0]-1,
            designSha256=file_sha(design_path),implementationSha256=file_sha(Path(__file__)))
        (output/f'{resource}-selection.json').write_text(json.dumps(selection,indent=2)+'\n')
        np.savez_compressed(output/f'{resource}-rolling-predictions.npz',**data,**{f'{k}_raw':v for k,v in raw.items()})
        print(resource,'SELECTION FROZEN',selection['winner'],selection['referenceWeights'],selection['regionalWeights'],flush=True)
    (output/'selection-frozen.json').write_text(json.dumps(dict(
        designSha256=file_sha(design_path),datasetSha256=dataset.sha256,
        selections={r:file_sha(output/f'{r}-selection.json') for r in ('CPU','GPU')}),indent=2)+'\n')


def cohort_report(actual,current,pred,reference,origin,horizon,pool,identities):
    result=metrics(actual,pred,current)
    ref_mae=float(np.abs(actual-reference).mean())
    result['maeReductionVsReferencePct']=100*(1-result['mae']/ref_mae) if ref_mae else None
    rows=[]
    for p in np.unique(pool):
        mask=pool==p
        rows.append(dict(identity=identities[int(p)],**metrics(actual[mask],pred[mask],current[mask])))
    result.update(byPool=rows,poolSummary=dict(improved=sum(r['mae']<r['persistenceMae'] for r in rows),
        worsened=sum(r['mae']>r['persistenceMae'] for r in rows),tied=sum(r['mae']==r['persistenceMae'] for r in rows)),
        byHorizon={str(h):metrics(actual[horizon==h],pred[horizon==h],current[horizon==h]) for h in range(1,7)})
    if origin.max()-origin.min()>=48:
        result['timeBlockDiagnosticVsReference']=block_diagnostic(origin,actual,pred,reference,48)
    else:
        result['timeBlockDiagnosticVsReference']=dict(status='INSUFFICIENT_TIME_BLOCKS')
    return result


def run_evaluation(original,public,output,models_output,design_path):
    if (output/'evaluation.json').exists() or models_output.exists():
        raise ValueError('Do not overwrite policy diagnostics or model bundles')
    design,dataset=load_inputs(original,public,design_path)
    frozen=json.loads((output/'selection-frozen.json').read_text())
    if frozen['designSha256']!=file_sha(design_path) or frozen['datasetSha256']!=dataset.sha256:
        raise ValueError('Selection/dataset mismatch')
    selections={}
    for r,sha in frozen['selections'].items():
        if file_sha(output/f'{r}-selection.json')!=sha:
            raise ValueError('Selection was modified after freezing')
        selections[r]=json.loads((output/f'{r}-selection.json').read_text())
    models_output.mkdir(parents=True,exist_ok=False)
    report=dict(design=design,selectionFreezeSha256=file_sha(output/'selection-frozen.json'),
        datasetSha256=dataset.sha256,resources={},
        implementationSha256=file_sha(Path(__file__)))
    for resource in ('CPU','GPU'):
        arrays,identities,hardware=build_matrix(dataset,resource)
        selection=selections[resource]
        train=arrays['origin']+6<design['finalTrainEndExclusive']
        final_models={'pooled':ErrorPriceModel(ROOT/'models/public-region-001',resource)}
        regional={}
        for region in sorted(set(arrays['region'])):
            if region=='eu-north-1':
                regional[region]=ErrorPriceModel(ROOT/'models/error-reduction-001',resource)
            else:
                regional[region]=fit_model(arrays,train&(arrays['region']==region),identities,hardware,design,
                    models_output,resource+'-'+region)
                print(resource,'FINAL',region,'complete',flush=True)
        resource_report=dict(selection=selection,periods={})
        for name,(start,end) in design['evaluation'].items():
            is_original=name.startswith('stockholm')
            score=(arrays['origin']>=start)&(arrays['origin']+6<end)&(
                (arrays['region']=='eu-north-1') if is_original else (arrays['region']!='eu-north-1'))
            assert selection['selectionMaxTargetSlot']<arrays['origin'][score].min()
            assert (arrays['origin'][train]+arrays['horizon'][train]).max()<arrays['origin'][score].min()
            current=arrays['current'][score];actual=arrays['actual'][score];regions=arrays['region'][score]
            raw={'persistence':current.copy(),'pooled':predict(final_models['pooled'],arrays,score),'regional':current.copy()}
            for region,model in regional.items():
                mask=score&(arrays['region']==region)
                raw['regional'][regions==region]=predict(model,arrays,mask)
            reference=route_predictions(raw,regions,selection['referenceChoices'])
            routed=route_predictions(raw,regions,selection['regionalChoices'])
            pred=dict(persistence=current,reference=reference,regional=raw['regional'],
                **{'reference-blend':blend(current,reference,arrays['horizon'][score],selection['referenceWeights']),
                   'validation-route-blend':blend(current,routed,arrays['horizon'][score],selection['regionalWeights'])})
            pred['selected']=pred[selection['winner']]
            cohort={key:arrays[key][score] for key in ('origin','horizon','pool','actual','current','region')}
            resource_report['periods'][name]={key:cohort_report(actual,current,values,reference,
                cohort['origin'],cohort['horizon'],cohort['pool'],identities) for key,values in pred.items()}
            np.savez_compressed(output/f'{resource}-{name}-predictions.npz',**cohort,
                **{key.replace('-','_'):value for key,value in pred.items()})
            chosen=resource_report['periods'][name]['selected']
            print(resource,name,'SELECTED vs persistence',chosen['maeImprovementPct'],
                  'vs reference',chosen['maeReductionVsReferencePct'],flush=True)
        report['resources'][resource]=resource_report
        (output/'evaluation.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    bundle=dict(designSha256=file_sha(design_path),selectionFreezeSha256=file_sha(output/'selection-frozen.json'),
        status='EXPERIMENTAL_NOT_DEPLOYED',resources=selections,
        pooledModels='models/public-region-001',stockholmRegionalModels='models/error-reduction-001',
        additionalRegionalModels=(str(models_output.resolve().relative_to(ROOT))
            if models_output.resolve().is_relative_to(ROOT) else str(models_output.resolve())),
        note='Regional expert metadata, native weights and source pool encodings are stored alongside this policy. Existing base bundles remain immutable.')
    (models_output/'policy.json').write_text(json.dumps(bundle,indent=2)+'\n')
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('original','public','output','design'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['select','evaluate'],required=True)
    parser.add_argument('--models-output',type=Path)
    args=parser.parse_args()
    if args.phase=='select':
        run_selection(args.original,args.public,args.output,args.design)
    else:
        if args.models_output is None:parser.error('--models-output is required for evaluation')
        run_evaluation(args.original,args.public,args.output,args.models_output,args.design)
