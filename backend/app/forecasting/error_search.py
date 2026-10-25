"""Reproducible post-holdout development search; never a new blind test."""
from pathlib import Path
import json
import hashlib
import numpy as np
import lightgbm as lgb
from app.forecasting.training_data import load_prepared_dataset


def causal_matrix(series, end_slot):
    """Features only use observations at or before the forecast origin."""
    p = np.array([series.prices.get(t) if series.prices.get(t) is not None else np.nan
                  for t in range(end_slot)], dtype=float)
    origins = np.arange(168, end_slot-6)
    history = np.stack([p[origins-k] for k in range(169)], axis=1)
    valid = np.isfinite(history).all(axis=1) & (history[:, 0] > 0)
    origins, history = origins[valid], history[valid]
    current = history[:, 0]
    relative = history/current[:, None]-1
    cols = [current]
    for lag in (1,2,3,4,6,8,12,18,24,36,48,72,96,120,144,168):
        cols.append(relative[:, lag])
    for window in (3,6,12,24,48,72,168):
        block = relative[:, :window]
        changes = np.diff(history[:, :window+1], axis=1)
        cols.extend([block.mean(axis=1), block.std(axis=1), block.min(axis=1),
                     block.max(axis=1), (changes != 0).mean(axis=1)])
    changed = history[:, :-1] != history[:, 1:]
    cols.append(np.where(changed.any(axis=1), changed.argmax(axis=1), 168))
    cols.extend([np.sin(2*np.pi*origins/24), np.cos(2*np.pi*origins/24),
                 (origins//24+1)%7])  # origin is Tuesday 2026-07-28
    base = np.stack(cols, axis=1)
    x = np.repeat(base, 6, axis=0)
    o = np.repeat(origins, 6)
    h = np.tile(np.arange(1,7), len(origins))
    x = np.column_stack([x, h, np.sin(2*np.pi*(o+h)/24), np.cos(2*np.pi*(o+h)/24)])
    c = np.repeat(current, 6)
    return x.astype(np.float32), o, h, c, p[o+h]


def metrics(actual, pred, current):
    mae = float(np.mean(np.abs(actual-pred)))
    base = float(np.mean(np.abs(actual-current)))
    return dict(mae=mae, rmse=float(np.sqrt(np.mean((actual-pred)**2))),
                persistenceMae=base, maeImprovementPct=100*(1-mae/base) if base else None,
                sampleCount=len(actual))


def run(dataset_path, output):
    output.mkdir(parents=True, exist_ok=False)
    dataset = load_prepared_dataset(dataset_path)
    candidates = [dict(name=f'{target}-l1-{leaves}', target=target, leaves=leaves)
                  for target in ('relative', 'scaled') for leaves in (7,31)]
    candidates += [dict(name='relative-l2-31', target='relative', leaves=31, objective='regression')]
    design = dict(status='POST_HOLDOUT_DEVELOPMENT_NOT_BLIND', seed=42,
                  trainEnd=1257, selection=[1257,1578], confirmation=[1791,2112],
                  candidates=candidates, weights=[.5,1.0], rounds=200,
                  datasetSha256=dataset.sha256,
                  implementationSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'design.json').write_text(json.dumps(design, indent=2))
    results = dict(design=design, resources={})
    for resource in ('CPU','GPU'):
        matrices=[]; origins=[]; horizons=[]; currents=[]; actuals=[]; ids=[]
        pools = [s for s in dataset.series if s.identity.resource_type == resource]
        hardware = sorted({s.identity.gpu_type or s.identity.instance_type.split('.')[0] for s in pools})
        for idx,s in enumerate(pools):
            x,o,h,c,a=causal_matrix(s,2112)
            hw = hardware.index(s.identity.gpu_type or s.identity.instance_type.split('.')[0])
            matrices.append(np.column_stack([x,np.full(len(x),idx),np.full(len(x),hw)]))
            origins.append(o); horizons.append(h); currents.append(c); actuals.append(a); ids.append(np.full(len(x),idx))
        x=np.concatenate(matrices).astype(np.float32); o=np.concatenate(origins); h=np.concatenate(horizons)
        c=np.concatenate(currents); a=np.concatenate(actuals); pool=np.concatenate(ids)
        del matrices
        train=(o+6<1257)
        supported=np.unique(pool[train]); eligible=np.isin(pool,supported)
        validation=(o>=1257)&(o+6<1578)
        confirmation=(o>=1791)&(o+6<2112)
        score=validation|confirmation
        scale=float(np.median(c[train]))
        reports=[]; predictions={}
        print(resource, 'matrix',x.shape,'train',int(train.sum()),flush=True)
        for spec in candidates:
            divisor=c if spec['target']=='relative' else np.full(len(c),scale)
            target=(a-c)/divisor
            weights=divisor[train]/scale
            params=dict(objective=spec.get('objective','regression_l1'),num_leaves=spec['leaves'],
                        learning_rate=.04,min_data_in_leaf=100,lambda_l2=1,
                        verbosity=-1,num_threads=1,seed=42,deterministic=True,force_col_wise=True)
            model=lgb.train(params,lgb.Dataset(x[train],label=target[train],weight=weights,
                                             categorical_feature=[x.shape[1]-2,x.shape[1]-1]),num_boost_round=200)
            delta=model.predict(x[score],num_threads=1)*divisor[score]
            delta[~eligible[score]]=0
            model.save_model(str(output/f'{resource}-{spec["name"]}.txt'))
            for weight in (.5,1.):
                pred=np.maximum(0,c[score]+weight*delta)
                name=f'{spec["name"]}-w{weight}'
                report=dict(name=name,selection=metrics(a[validation],pred[validation[score]],c[validation]))
                reports.append(report); predictions[name]=pred
                print(resource,name,report['selection']['maeImprovementPct'],flush=True)
        # Freeze selection before inspecting confirmation metrics.
        winner=min(reports,key=lambda r:r['selection']['mae'])['name']
        (output/f'{resource}-selection.json').write_text(json.dumps(dict(winner=winner,candidates=reports),indent=2))
        for report in reports:
            pred=predictions[report['name']]
            report['confirmation']=metrics(a[confirmation],pred[confirmation[score]],c[confirmation])
        pred=predictions[winner][confirmation[score]]
        by_pool=[]
        for idx,s in enumerate(pools):
            mask=pool[confirmation]==idx
            if mask.any():
                by_pool.append(dict(identity=s.identity.to_dict(),**metrics(a[confirmation][mask],pred[mask],c[confirmation][mask])))
        results['resources'][resource]=dict(winner=winner,candidates=reports,byPool=by_pool,
            fallbackConfirmationCount=int((confirmation&~eligible).sum()))
        np.savez_compressed(output/f'{resource}-winner-predictions.npz',origin=o[confirmation],horizon=h[confirmation],
                            pool=pool[confirmation],actual=a[confirmation],persistence=c[confirmation],prediction=pred)
        (output/'report.json').write_text(json.dumps(results,indent=2))
        print(resource,'WINNER',winner,next(r for r in reports if r['name']==winner),flush=True)
    return results

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.dataset,args.output)
