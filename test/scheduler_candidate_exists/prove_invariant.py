#!/usr/bin/env python3
"""证明保存的候选存在性与当前帧目录在复位及每一步更新后相同。"""
from pathlib import Path
import argparse,hashlib,json,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/control/ps_window_scheduler.sv')
p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--profiles',nargs='+',default=['4:4:4','16:16:32']);a=p.parse_args()
a.out.mkdir(parents=True,exist_ok=True)
src=a.source_root/RTL;text=src.read_text()
text=text.replace('lookahead_count_k);','lookahead_count_k,\n    output logic formal_hold_ok);',1)
body='''
    // 验证副本输出：保存的候选存在性与当前帧目录一致。
    assign formal_hold_ok = candidate_exists == (|(live & frame_open));
'''
text=text.replace('`ifdef NPU_SIM_ASSERT',body+'\n`ifdef NPU_SIM_ASSERT',1)
ver=a.out/'scheduler.sv';ver.write_text(text)
common=sorted(p for p in (a.source_root/'rtl/common').glob('*') if p.suffix in ['.sv','.v']);rows=[]
for profile in a.profiles:
 size,frames,reuse=map(int,profile.split(':'));stem=profile.replace(':','_');out=a.out/stem;out.mkdir(exist_ok=True)
 commands=[f'read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 -GSIZE={size} -GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} --top ps_window_scheduler '+shlex.join(map(str,[ver,*common])), 'prep -top ps_window_scheduler -flatten','memory_map','async2sync','opt_clean','sat -verify -seq 1 -set rst_n 0 -prove formal_hold_ok 1 -show formal_hold_ok','sat -verify -tempinduct -tempinduct-inductonly -seq 1 -maxsteps 1 -timeout 45 -prove formal_hold_ok 1 -show formal_hold_ok -show candidate_exists -show live -show frame_open -show phase -dump_json '+str(out/'counterexample.json')]
 script=out/'prove.ys';script.write_text('\n'.join(commands)+'\n')
 with (out/'proof.log').open('w') as f:r=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=f,stderr=subprocess.STDOUT,timeout=90)
 row={'profile':profile,'passed':r.returncode==0,'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest()};rows.append(row);print(json.dumps(row),flush=True)
 if r.returncode:break
(a.out/'summary.json').write_text(json.dumps({'profiles':rows,'passed':all(r['passed'] for r in rows)},indent=2)+'\n')
if not all(row['passed'] for row in rows):
 raise SystemExit(1)
