#!/usr/bin/env python3
"""在明确的宏配置下比较完整窗口缓存的输出与保存状态。"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys,runpy,shlex,subprocess,re,json,hashlib,argparse
root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--reference',default='548bda54')
args=parser.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
reference=out/'reference.sv'
reference.write_bytes(subprocess.check_output(['git','show',args.reference+':rtl/npu/dma/cache/conv_windowed_cache.sv'],cwd=root))
resolver=runpy.run_path(str(root/'scripts/rtl/source_files.py'))['with_dependencies']
profiles=[dict(SETS=2,WAYS=1,LINE_BYTES=8,BUS_WIDTH=32,READ_WIDTH=32,DEMAND_DEPTH=1),dict(SETS=2,WAYS=2,LINE_BYTES=16,BUS_WIDTH=32,READ_WIDTH=32,DEMAND_DEPTH=2),dict(SETS=4,WAYS=1,LINE_BYTES=32,BUS_WIDTH=64,READ_WIDTH=64,DEMAND_DEPTH=4),dict(SETS=16,WAYS=2,LINE_BYTES=128,BUS_WIDTH=64,READ_WIDTH=64,DEMAND_DEPTH=2)]
sources={n:resolver([path],root) for n,path in [('reference',reference),('current',root/'rtl/npu/dma/cache/conv_windowed_cache.sv')]}
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for ps in sources.values() for p in ps}
cases=[]
for mode,flags in [('generic',['-USYNTHESIS']),('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]:
 for index,params in enumerate(profiles):
  options=[f'-G{k}={v}' for k,v in params.items()];commands=[]
  for label,paths in sources.items():
   commands += ['read_slang --top conv_windowed_cache '+shlex.join(flags+options+list(map(str,paths))),
    'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
    'prep -top conv_windowed_cache -flatten','memory_map','async2sync','opt -full',f'rename -top {label}',f'design -stash {label}']
  commands += ['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current proof','hierarchy -top proof','equiv_struct -icells -fwd t:* t:$reduce_and %d t:$reduce_or %d t:$reduce_bool %d','select *','equiv_induct -seq 2','equiv_simple -seq 1','opt_clean','equiv_status -assert']
  script=out/f'{mode}_{index}.ys';log=out/f'{mode}_{index}.log';script.write_text('\n'.join(commands)+'\n');cases.append((mode,params,script,log))
def execute(case):
 mode,params,script,log=case
 with log.open('w') as f:subprocess.run([sys.executable,str(root/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=600)
 text=log.read_text();counts=re.findall(r'Found (\d+) \$equiv cells',text);assert counts and 'Equivalence successfully proven!' in text
 result={'mode':mode,'parameters':params,'bits':int(counts[-1]),'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()};print(json.dumps(result),flush=True);return result
with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(execute,cases))
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
report={'passed':True,'reference_commit':args.reference,'source_sha256':hashes,'input_constraints':[],'parent_outputs_and_state_every_cycle':True,'formal':results};(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
