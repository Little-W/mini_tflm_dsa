#!/usr/bin/env python3
"""比较预取描述与快照匹配保存后的完整四态周期行为。"""
from pathlib import Path
import argparse,hashlib,json,subprocess
RTL=Path('rtl/npu/dma/cache/conv_read_cache.sv')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def model(label,text,si):
 start=text.index('  logic [3:0] offer_read_set_match_q;')if'  logic [3:0] offer_read_set_match_q;'in text else text.index('  wire incoming_lookup_ready =')
 end=text.index('\n\n  // 地址范围比较',start)
 code=text[start:end]
 return f'''module {label}(input wire clk,input wire [4+3*{si}-1:0] stimulus,output wire [1:0] ready);
 localparam integer SI={si};
 wire rst_n,offer_capture,metadata_enable,metadata_fill_good;
 wire [SI-1:0] initial_pf_set,next_pf_set,fill_set;
 assign {{rst_n,offer_capture,metadata_enable,metadata_fill_good,initial_pf_set,next_pf_set,fill_set}}=stimulus;
 logic [SI-1:0] incoming_snapshot_set,next_snapshot_set,incoming_hold_snapshot_set,next_hold_snapshot_set;
 logic incoming_snapshot_valid,next_snapshot_valid,incoming_hold_snapshot_valid,next_hold_snapshot_valid;
 logic [SI-1:0] offer_set_q,offer_next_set_q;
 logic offer_fresh_q;
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin incoming_snapshot_valid<=0;next_snapshot_valid<=0;incoming_hold_snapshot_valid<=0;next_hold_snapshot_valid<=0;end
  else begin
   incoming_snapshot_set<=initial_pf_set;next_snapshot_set<=next_pf_set;
   incoming_hold_snapshot_set<=offer_set_q;next_hold_snapshot_set<=offer_next_set_q;
   incoming_snapshot_valid<=!(metadata_enable&&metadata_fill_good&&fill_set==initial_pf_set);
   next_snapshot_valid<=!(metadata_enable&&metadata_fill_good&&fill_set==next_pf_set);
   incoming_hold_snapshot_valid<=!(metadata_enable&&metadata_fill_good&&fill_set==offer_set_q);
   next_hold_snapshot_valid<=!(metadata_enable&&metadata_fill_good&&fill_set==offer_next_set_q);
  end
 end
 always_ff @(posedge clk or negedge rst_n)if(!rst_n)offer_fresh_q<=0;else offer_fresh_q<=offer_capture;
 always_ff @(posedge clk)if(offer_capture)begin offer_set_q<=initial_pf_set;offer_next_set_q<=next_pf_set;end
 {code}
 assign ready={{next_lookup_ready,incoming_lookup_ready}};
endmodule
'''
def bench(si):
 width=4+3*si
 return f'''module tb;
 localparam integer WIDTH={width};
 logic clk=0;
 logic [WIDTH-1:0] stimulus=0,saved;
 wire [1:0] a,b;
 reference ref_model(clk,stimulus,a);current current_model(clk,stimulus,b);
 reg [31:0] rng=32'h174a852f;
 integer checks=0,unknown_trials=0;
 task check;
  #1;if(a!==b)$fatal(1,"快照资格不同 input=%b clock=%b reference=%b current=%b",stimulus,clk,a,b);checks++;
 endtask
 task randomize;
  for(integer k=0;k<WIDTH;k++)begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);stimulus[k]=rng[0];end
 endtask
 task tick;
  check();clk=1;check();clk=0;check();
 endtask
 initial begin
  tick();stimulus[WIDTH-1]=1;tick();
  for(integer cycle=0;cycle<4096;cycle++)begin randomize();tick();end
  for(integer trial=0;trial<256;trial++)begin
   randomize();stimulus[WIDTH-1]=1;tick();saved=stimulus;
   for(integer k=0;k<WIDTH;k++)begin
    stimulus=saved;stimulus[k]=1'bx;tick();unknown_trials++;
    stimulus=saved;check();tick();
    stimulus=saved;stimulus[k]=1'bz;tick();unknown_trials++;
    stimulus=saved;check();tick();
   end
  end
  stimulus='x;tick();stimulus='z;tick();stimulus='0;tick();stimulus='1;tick();
  $display("{{\\"passed\\":true,\\"checks\\":%0d,\\"unknown_trials\\":%0d}}",checks,unknown_trials);$finish;
 end
endmodule
'''
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 paths={'reference':a.reference_root.resolve()/RTL,'current':a.source_root.resolve()/RTL};manifest={str(f):sha(f)for f in [*paths.values(),Path(__file__).resolve()]};runs=[]
 for si in [1,2,4,5]:
  source=out/f'si{si}.sv';source.write_text('\n'.join(model(label,path.read_text(),si)for label,path in paths.items())+bench(si));binary=out/f'si{si}.vvp'
  with (out/f'si{si}.compile.log').open('w')as stream:subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(source)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
  result=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,timeout=120);log=out/f'si{si}.log';log.write_text(result.stdout+result.stderr)
  if result.returncode:raise RuntimeError(str(log))
  row=json.loads(next(line for line in result.stdout.splitlines()if line.startswith('{')));row.update(SI=si,bench_sha256=sha(source),log_sha256=sha(log));runs.append(row);print(json.dumps(row),flush=True)
 if any(sha(Path(p))!=h for p,h in manifest.items()):raise RuntimeError('源文件发生变化')
 (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=manifest,profiles=runs,checks=sum(r['checks']for r in runs)),indent=2)+'\n')
if __name__=='__main__':main()
