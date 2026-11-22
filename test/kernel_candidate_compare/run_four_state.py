#!/usr/bin/env python3
"""对实际描述符比较器的二值和四态输入逐项比较。"""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/loaders/kernel_loader.sv')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def helper(text):
 start=text.index('module kernel_candidate_equal #(')
 return text[start:text.index('endmodule',start)+len('endmodule')]

def module_path(root):
 path=root.resolve()/RTL.with_name('kernel_candidate_equal.sv')
 return path if path.is_file()else root.resolve()/RTL

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--source-root',type=Path,default=ROOT);p.add_argument('--reference-root',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True);p.add_argument('--widths',nargs='+',type=int,default=[1,2,3,5,31,32,33,99,160])
 a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);sources={label:module_path(folder) for label,folder in [('reference',a.reference_root),('current',a.source_root)]};hashes={str(f):digest(f)for f in [*sources.values(),Path(__file__).resolve()]};models='\n'.join(helper(f.read_text()).replace('kernel_candidate_equal',label+'_equal')for label,f in sources.items());rows=[]
 for width in a.widths:
  folder=out/str(width);folder.mkdir(exist_ok=True)
  bench=f'''module tb;
 logic[{width-1}:0] a,b,saved_a,saved_b;
 wire reference_equal,current_equal;
 integer checks=0;
 reference_equal #(.p_width({width})) r(a,b,reference_equal);
 current_equal #(.p_width({width})) c(a,b,current_equal);
 task compare;
  #1;if(reference_equal!==current_equal)$fatal(1,"描述符比较不同 width={width} a=%h b=%h",a,b);
  checks++;
 endtask
 initial begin
  a='0;b='0;compare();a='1;b='1;compare();a='x;b='x;compare();a='z;b='z;compare();
  for(integer trial=0;trial<4096;trial++)begin
   for(integer bit_index=0;bit_index<{width};bit_index++)begin a[bit_index]=$urandom;b[bit_index]=$urandom;end
   if(trial%4==0)b=a;compare();
  end
  for(integer trial=0;trial<8;trial++)begin
   for(integer bit_index=0;bit_index<{width};bit_index++)a[bit_index]=$urandom;
   b=a;saved_a=a;saved_b=b;
   for(integer bit_index=0;bit_index<{width};bit_index++)begin
    a=saved_a;b=saved_b;a[bit_index]=1'bx;compare();a[bit_index]=1'bz;compare();
    a=saved_a;b=saved_b;b[bit_index]=1'bx;compare();b[bit_index]=1'bz;compare();
   end
  end
  $display("{{\\"passed\\":true,\\"checks\\":%0d}}",checks);$finish;
 end
endmodule
'''
  source=folder/'tb.sv';source.write_text(models+'\n'+bench);binary=folder/'sim.vvp'
  with (folder/'compile.log').open('w')as f:subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(source)],stdout=f,stderr=subprocess.STDOUT,check=True)
  result=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,check=True);log=folder/'run.log';log.write_text(result.stdout+result.stderr);row=json.loads(next(line for line in result.stdout.splitlines()if line.startswith('{')));row.update(width=width,log_sha256=digest(log));rows.append(row);print(json.dumps(row),flush=True)
 if any(digest(Path(f))!=h for f,h in hashes.items()):raise RuntimeError('验证期间源码发生变化')
 (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,profiles=rows,checks=sum(r['checks']for r in rows)),indent=2)+'\n')
if __name__=='__main__':main()
