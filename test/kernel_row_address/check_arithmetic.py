#!/usr/bin/env python3
"""提取生产行首地址加法，比较定宽结果及未知输入传播。"""
from pathlib import Path
import argparse,hashlib,json,runpy,subprocess
ROOT=Path(__file__).resolve().parents[2]

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--out',type=Path,required=True)
 args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
 source=ROOT/'rtl/npu/loaders/kernel_loader_ctrl.sv';text=source.read_text()
 start=text.index('  logic [REG_WIDTH-1:0] row_base_address_fast;')
 end=text.index('  assign dma_address_increment',start)
 body=text[start:end]
 model=out/'row_address_proof.sv'
 model.write_text("""// 生产地址表达式与完整模宽加法的比较。
module row_address_proof #(parameter REG_WIDTH=32)(
 input logic [REG_WIDTH-1:0] row_base_address_q, // 当前行首地址
 input logic [REG_WIDTH-1:0] row_addr_step, // 下一行的字节间隔
 output logic equal // 地址结果与完整模宽加法一致
);
logic [REG_WIDTH-1:0] row_base_address_increment;
"""+body+"assign equal=row_base_address_increment===(row_base_address_q+row_addr_step);\nendmodule\n")
 resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
 sources=resolve([model],ROOT);hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,*sources]};results=[]
 for width in (16,32,64):
  for synthesis in (False,True):
   name=f'w{width}_s{int(synthesis)}';bench=out/(name+'.sv');binary=out/(name+'.vvp')
   bench.write_text(f"""module tb;
localparam W={width};
logic [W-1:0] row_base_address_q,row_addr_step;wire equal;integer checks=0;
row_address_proof #(.REG_WIDTH(W)) dut(.*);
initial begin
 for(integer sample=0;sample<8192;sample++)begin
  row_base_address_q={{$urandom,$urandom}};row_addr_step={{$urandom,$urandom}};
  case(sample%8)
   0:row_base_address_q[(sample/8)%W]=1'bx;
   1:row_base_address_q[(sample/8)%W]=1'bz;
   2:row_addr_step[(sample/8)%W]=1'bx;
   3:row_addr_step[(sample/8)%W]=1'bz;
   4:begin row_base_address_q='1;row_addr_step=1;end
   5:begin row_base_address_q='1;row_addr_step='1;end
   6:begin row_base_address_q=0;row_addr_step=0;end
   default:begin end
  endcase
  #1;if(equal!==1'b1)$fatal(1,"Row address differs width=%0d sample=%0d",W,sample);checks++;
 end
 $display("ROW_ADDRESS_PASS width=%0d checks=%0d",W,checks);$finish;
end
endmodule
""")
   flags=['-DSYNTHESIS=1','-DXILINX_FPGA=1'] if synthesis else []
   with (out/(name+'_compile.log')).open('w') as f:subprocess.run(['iverilog','-g2012','-s','tb',*flags,'-o',str(binary),*map(str,sources),str(bench)],stdout=f,stderr=subprocess.STDOUT,check=True)
   result=subprocess.check_output(['vvp',str(binary)],text=True,timeout=120);(out/(name+'_simulation.log')).write_text(result)
   assert f'ROW_ADDRESS_PASS width={width} checks=8192' in result
   results.append({'width':width,'synthesis':synthesis,'four_state_comparisons':8192,'passed':True,'log_sha256':hashlib.sha256(result.encode()).hexdigest()});print(name,'PASS',flush=True)
 assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
 (out/'validation.json').write_text(json.dumps({'passed':True,'source_sha256':hashes,'checks':results,'four_state_comparisons':49152},indent=2)+'\n')
if __name__=='__main__':main()
