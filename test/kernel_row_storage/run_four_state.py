#!/usr/bin/env python3
"""检查实际权重存储器的四态输出、复位和同址读写行为。"""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];RTL=Path('rtl/npu/loaders/kernel_loader_buffer.sv')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True)
 p.add_argument('--profiles',nargs='+',default=['3:8','4:16','16:8','16:16','32:16']);p.add_argument('--out',type=Path,required=True)
 a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 src=a.source_root.resolve()/RTL;old=a.reference_root.resolve()/RTL;mem=a.source_root.resolve()/'rtl/common/regfile.v';tb=Path(__file__).with_name('tb_four_state.sv')
 hashes={str(x):digest(x)for x in(src,old,mem,tb)};ref=out/'kernel_loader_buffer_ref.sv';cur=out/'kernel_loader_buffer.sv'
 ref.write_text(old.read_text().replace('kernel_loader_buffer','kernel_loader_buffer_ref').replace('parameter int unsigned','parameter integer'))
 cur.write_text(src.read_text().replace('parameter int unsigned','parameter integer'))
 reports=[]
 for profile in a.profiles:
  n,w=map(int,profile.split(':'));folder=out/f'n{n}_w{w}';folder.mkdir(exist_ok=True);binary=folder/'simulation.vvp'
  cmd=['iverilog','-g2012','-s','tb_kernel_buffer_four_state',f'-Ptb_kernel_buffer_four_state.SIZE={n}',f'-Ptb_kernel_buffer_four_state.DATA_WIDTH={w}','-o',str(binary),str(cur),str(ref),str(mem),str(tb)]
  with(folder/'compile.log').open('w')as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
  r=subprocess.run(['vvp',str(binary)],text=True,capture_output=True);(folder/'run.log').write_text(r.stdout+r.stderr)
  if r.returncode or 'BUFFER_FOUR_STATE_PASS'not in r.stdout:raise RuntimeError(str(folder/'run.log'))
  match=re.search(r'BUFFER_FOUR_STATE_PASS (.*)',r.stdout);counts={k:int(v)for k,v in re.findall(r'(\w+)=(\d+)',match[1])}
  row={'SIZE':n,'DATA_WIDTH':w,'passed':True,**counts};reports.append(row);print(json.dumps(row),flush=True)
 if any(digest(Path(k))!=v for k,v in hashes.items()):raise RuntimeError('源文件在测试期间发生变化')
 (out/'summary.json').write_text(json.dumps({'passed':True,'source_sha256':hashes,'profiles':reports,'checks':sum(r['checks']for r in reports)},indent=2)+'\n')
if __name__=='__main__':main()
