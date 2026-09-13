import json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[3]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
from runtime import run_case,report_line
from learned_search.scheduler import LearnedSearchScheduler
base={'schema':'learned_search_v1','features':['gain_per_cost','cluster','radius_norm','distance_norm','bearing_count','unknown_pressure','same_channel'],'bias':0.0}
cands={}
for d in [-2.5,-2.75,-3.0,-3.25]:
 for s in [.5,.6,.7,.8]:cands[f'd{d}_s{s}']=[1.0,.2,.2,d,.10,.06,s]
root=HERE/'experiments'/'q4_weight_search'/'refine2';
for name,w in cands.items():
 d=root/name;d.mkdir(exist_ok=True);(d/'model.json').write_text(json.dumps({**base,'weights':w,'source':'refine2'},indent=2)+'\n',encoding='utf-8')
seeds=[101,202,303,404,505];common={'nbv_mode':'radius','opportunistic_reuse':True,'cert_route_mode':'lookahead2','q4_joint_rank':True,'q4_residual_sparsify':True,'q4_certificate_layout':'sparse25'}
summary=[]
for name,w in cands.items():
 vals=[];oks=[]
 for seed in seeds:
  rep=run_case('Q4',seed,16,'mixed',LearnedSearchScheduler,root/name/f'seed_{seed}',scheduler_kwargs={**common,'model_path':str(root/name/'model.json')})
  row=report_line(rep);vals.append(row['T_per_source_s']);oks.append(row['complete'] and row['verifier_all_ok'])
 summary.append({'name':name,'weights':w,'mean':sum(vals)/len(vals),'values':vals,'ok':all(oks)}); print(name,round(sum(vals)/len(vals),3),all(oks))
summary.sort(key=lambda x:x['mean']);(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8');print('TOP');[print(x['name'],round(x['mean'],3),x['values']) for x in summary[:10]]
