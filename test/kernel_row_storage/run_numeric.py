#!/usr/bin/env python3
"""逐周期比较权重缓存的全部输出、数据及槽位释放。"""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/loaders/kernel_loader_buffer.sv')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--source-root',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True)
 p.add_argument('--profiles',nargs='+',default=['3:8','4:16','16:8','16:16','32:16'])
 p.add_argument('--cycles',type=int,default=100000);p.add_argument('--out',type=Path,required=True)
 a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 src=a.source_root.resolve()/RTL;old=a.reference_root.resolve()/RTL;mem=a.source_root.resolve()/'rtl/common/regfile.v'
 bench=ROOT/'test/kernel_prefetch/tb_buffer_equivalence.sv';hashes={str(x):digest(x)for x in(src,old,mem,bench)}
 ref=out/'kernel_loader_buffer_ref.sv';ref.write_text(old.read_text().replace('kernel_loader_buffer','kernel_loader_buffer_ref'))
 reports=[]
 for profile in a.profiles:
  n,w=map(int,profile.split(':'));folder=out/f'n{n}_w{w}';folder.mkdir(exist_ok=True)
  cmd=['verilator','--binary','--timing','-Wno-fatal','-j','1','--top-module','tb_kernel_buffer_equivalence','--Mdir',str(folder/'obj'),f'-GSIZE={n}',f'-GDATA_WIDTH={w}',f'-GRANDOM_CYCLES={a.cycles}',str(src),str(mem),str(bench),str(ref)]
  with(folder/'compile.log').open('w')as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
  binary=folder/'obj/Vtb_kernel_buffer_equivalence';r=subprocess.run([str(binary)],text=True,capture_output=True)
  (folder/'run.log').write_text(r.stdout+r.stderr)
  if r.returncode or 'KERNEL_BUFFER_EQ_PASS'not in r.stdout:raise RuntimeError(str(folder/'run.log'))
  match=re.search(r'KERNEL_BUFFER_EQ_PASS (.*)',r.stdout);counts={k:int(v)for k,v in re.findall(r'(\w+)=(\d+)',match[1])}
  row={'SIZE':n,'DATA_WIDTH':w,'passed':True,'binary_sha256':digest(binary),**counts};reports.append(row);print(json.dumps(row),flush=True)
  for obj in(folder/'obj').iterdir():
   if obj.suffix in('.o','.a','.gch'):obj.unlink()
 if any(digest(Path(k))!=v for k,v in hashes.items()):raise RuntimeError('源文件在测试期间发生变化')
 (out/'summary.json').write_text(json.dumps({'passed':True,'source_sha256':hashes,'compared_scalar_outputs':8,'compared_weight_lanes':'SIZE','profiles':reports},indent=2)+'\n')
if __name__=='__main__':main()
