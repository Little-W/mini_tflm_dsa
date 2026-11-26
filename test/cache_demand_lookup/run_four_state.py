#!/usr/bin/env python3
"""比较缓存组号选择和命中归并在二态及未知输入下的完整结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REQUEST = Path('rtl/npu/dma/cache/conv_cache_request_path.sv')
HIT = Path('rtl/npu/dma/cache/conv_cache_lookup_hit.sv')
REFERENCE = 'b805feb1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wrapper(label, text):
    if label == 'reference':
        begin = text.index('  conv_cache_metadata_eligibility u_demand_lookup (')
    else:
        begin = text.index('  (* keep = 1 *) logic demand_snapshot_set_match')
    end = text.index('  assign lookup_ready = fg_state == FG_MISS ?', begin)
    body = text[begin:end]
    return f'''module {label} #(parameter integer SI=4, WAYS=2)(
 input wire [3*SI+6+2*WAYS-1:0] stimulus, output wire [1:0] result);
 wire [SI-1:0] lookup_snapshot_set, demand_set, demand_fill_set;
 wire bypass_q, lookup_snapshot_valid, demand_word_matches_q, miss, filled, work_ready;
 wire [WAYS-1:0] demand_hits, work_hits;
 logic demand_lookup_ready;
 wire hit;
 assign {{lookup_snapshot_set,demand_set,demand_fill_set,bypass_q,lookup_snapshot_valid,
  demand_word_matches_q,miss,filled,work_ready,demand_hits,work_hits}}=stimulus;
{body}
 {"reference_hit" if label == 'reference' else "conv_cache_lookup_hit"} #(.p_ways(WAYS)) u_hit (
  .i_bypass(bypass_q),.i_miss(miss),.i_filled(filled),.i_demand_ready(demand_lookup_ready),
  .i_work_ready(work_ready),.i_demand_hits(demand_hits),.i_work_hits(work_hits),.o_hit(hit));
 assign result={{demand_lookup_ready,hit}};
endmodule
'''


def bench(si, ways):
    return f'''module tb;
 localparam integer SI={si},WAYS={ways},WIDTH=3*SI+6+2*WAYS;
 reg [WIDTH-1:0] stimulus,saved;
 wire [1:0] expected,actual;
 reference #(.SI(SI),.WAYS(WAYS)) u_reference(.*,.result(expected));
 current #(.SI(SI),.WAYS(WAYS)) u_current(.*,.result(actual));
 integer checks=0;
 reg [31:0] rng=32'h46aed319;
 task check;
  #1;if(expected!==actual)$fatal(1,"缓存查询结果不同 stimulus=%b expected=%b actual=%b",stimulus,expected,actual);
  checks++;
 endtask
 task randomize;
  for(integer k=0;k<WIDTH;k++)begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);stimulus[k]=rng[0];end
 endtask
 initial begin
  stimulus='0;check();stimulus='1;check();stimulus='x;check();stimulus='z;check();
  for(integer t=0;t<1024;t++)begin
   randomize();
   if(t%4==0)stimulus[WIDTH-1 -: 3*SI]='0;
   if(t%4==1)stimulus[WIDTH-1 -: 3*SI]='1;
   check();saved=stimulus;
   for(integer k=0;k<WIDTH;k++)begin
    stimulus=saved;stimulus[k]=1'bx;check();
    stimulus=saved;stimulus[k]=1'bz;check();
   end
   stimulus=saved;
   for(integer k=0;k<WIDTH;k++)begin
    rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
    if(rng[2:0]==0)stimulus[k]=1'bx;
    if(rng[2:0]==1)stimulus[k]=1'bz;
   end
   check();
  end
  $display("CACHE_DEMAND_LOOKUP_PASS checks=%0d",checks);$finish;
 end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old_request = subprocess.check_output(['git','show',REFERENCE+':'+str(REQUEST)],cwd=ROOT,text=True)
    old_hit = subprocess.check_output(['git','show',REFERENCE+':'+str(HIT)],cwd=ROOT,text=True)
    ref_hit = out/'reference_hit.sv'
    ref_hit.write_text(old_hit.replace('module conv_cache_lookup_hit','module reference_hit'))
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    helpers = resolver([ROOT/HIT, ROOT/'rtl/npu/dma/cache/conv_cache_demand_lookup.sv',
                        ROOT/'rtl/npu/dma/cache/conv_cache_metadata_eligibility.sv',
                        ROOT/'rtl/npu/dma/cache/conv_cache_demand_hit.sv',
                        ROOT/'rtl/npu/dma/cache/conv_cache_snapshot_response.sv'], ROOT)
    hashes = {str(p.relative_to(ROOT)):digest(p) for p in [ROOT/REQUEST,*helpers]}
    models = wrapper('reference',old_request)+wrapper('current',(ROOT/REQUEST).read_text())
    results=[]
    for mode,flags in [('generic',[]),('synthesis',['-DSYNTHESIS=1'])]:
        for si,ways in ((1,1),(2,2),(4,2),(8,4)):
            name=f'{mode}_s{si}_w{ways}'
            source,binary,log=out/(name+'.sv'),out/(name+'.vvp'),out/(name+'.log')
            source.write_text(models+bench(si,ways))
            with (out/(name+'.compile.log')).open('w') as stream:
                subprocess.run(['iverilog','-g2012',*flags,'-s','tb','-o',str(binary),str(source),str(ref_hit),*map(str,helpers)],
                               cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
            result=subprocess.run(['vvp',str(binary)],capture_output=True,text=True,check=True,timeout=180)
            log.write_text(result.stdout+result.stderr)
            count=re.search(r'CACHE_DEMAND_LOOKUP_PASS checks=(\d+)',result.stdout)
            assert count, str(log)
            results.append(dict(mode=mode,set_index_width=si,ways=ways,checks=int(count[1]),passed=True,
                                source_sha256=digest(source),log_sha256=digest(log)))
            binary.unlink()
            print(name,count[1],'PASS',flush=True)
    assert all(digest(ROOT/name)==value for name,value in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,reference=REFERENCE,
        source_sha256=hashes,profiles=results),ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
