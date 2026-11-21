#!/usr/bin/env python3
"""检查缓存读取位置与填充冲突在二值及四态输入下的结果。"""
import argparse, hashlib, json, math, re, subprocess
from pathlib import Path

RTL=Path('rtl/npu/dma/cache/conv_read_cache.sv')

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def model(label,text,sets,line,depth,bus,read):
    si=max(1,(sets-1).bit_length());aw=max(1,(depth-1).bit_length());cw=depth.bit_length();dw=si+30
    fields=[('fg_state',2),('req_fire',1),('req_valid',1),('request_count',cw),('request_head',aw),('bypass_q',1),('demand_set',si),('demand_fill_set',si),('demand_addr',32),('incoming_request',dw),('request_queue',depth*dw),('work_set',si),('fill_set',si),('span_addr',32),('ram_wen',1)]
    width=sum(w for _,w in fields)
    decl='\n'.join(f'wire [{w-1}:0] {n};' for n,w in fields if n!='request_queue')
    decl+=f'\nwire [DEMAND_DEPTH-1:0][SI+29:0] request_queue;'
    start=text.index('  always_comb begin\n    lookup_read_request = request_count==0')
    end=text.index('  // 填充组号与查询快照',start)
    select=text[start:end]
    select=select.replace('.address[31:2]','[SI+:30]').replace('.set_index','[SI-1:0]')
    select=select.replace("request_queue[DQ_AW'(request_head + DQ_AW'(1))]",'next_request').replace('request_queue[request_head]','head_request')
    start=text.index('  localparam int WAY_DEPTH =')
    end=text.index('  for (genvar data_way=',start)
    conflict=text[start:end]
    if 'logic lookup_fill_match;' not in select:
        select+='\nlogic lookup_fill_match;\nassign lookup_fill_match=fill_set==lookup_read_set;\n'
    lookup_set=re.search(r'  assign lookup_set =.*?;',text,re.S)[0].replace('work_request.set_index','work_set')
    code=f'''module {label}(input wire [{width-1}:0] stimulus,output wire [1:0] result);
 localparam integer SETS={sets}, LINE_BYTES={line}, DEMAND_DEPTH={depth}, BUS_WIDTH={bus}, READ_WIDTH={read};
 localparam integer SI={si}, DQ_AW={aw}, DQ_CW={cw};
 localparam [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
 {decl}
 assign {{{','.join(n for n,_ in fields)}}}=stimulus;
 logic [SI-1:0] lookup_set,lookup_read_set;
 logic [SI+29:0] lookup_read_request;
 wire [SI+29:0] head_request=request_queue[request_head];
 wire [SI+29:0] next_request=request_queue[DQ_AW'(request_head+DQ_AW'(1))];
 logic [31:2] lookup_read_word;
 logic spec_read_conflict;
 {lookup_set}
 {select}
 {conflict}
 assign result={{lookup_fill_match,spec_read_conflict}};
endmodule
'''
    return code,width

def bench(width):
    return f'''module tb;
 logic [{width-1}:0] stimulus=0,saved;
 wire [1:0] a,b;
 reference u_reference(stimulus,a);
 current u_current(stimulus,b);
 reg [31:0] rng=32'h87a91d4f;
 integer checks=0,unknown_checks=0,known_checks=0;
 task randomize;
 for(integer bit_index=0;bit_index<{width};bit_index++)begin
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);stimulus[bit_index]=rng[0];
 end
 endtask
 task check;
 #1;
 if(a!==b)$fatal(1,"读取冲突比较不同 input=%b reference=%b current=%b",stimulus,a,b);
 checks++;
 if((^a)===1'b0||(^a)===1'b1)known_checks++;
 endtask
 initial begin
 for(integer cycle=0;cycle<4096;cycle++)begin randomize();check();end
 for(integer trial=0;trial<128;trial++)begin
  randomize();saved=stimulus;
  for(integer bit_index=0;bit_index<{width};bit_index++)begin
   stimulus=saved;stimulus[bit_index]=1'bx;check();unknown_checks++;
   stimulus=saved;stimulus[bit_index]=1'bz;check();unknown_checks++;
  end
 end
 stimulus='x;check();stimulus='z;check();
 $display("{{\\"passed\\":true,\\"checks\\":%0d,\\"unknown_checks\\":%0d,\\"known_checks\\":%0d}}",checks,unknown_checks,known_checks);
 $finish;
 end
endmodule
'''

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--reference-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    paths={'reference':a.reference_root.resolve()/RTL,'current':a.source_root.resolve()/RTL};manifest={str(p):sha(p)for p in [*paths.values(),Path(__file__).resolve()]};records=[]
    for profile in [(2,16,2,32,32),(16,128,2,64,64),(32,64,4,128,32),(4,32,1,64,32),(16,128,4,32,64)]:
        name='_'.join(map(str,profile));modules=[]
        for label,path in paths.items():
            text,width=model(label,path.read_text(),*profile);modules.append(text)
        source=out/(name+'.sv');source.write_text('\n'.join(modules)+bench(width));binary=out/(name+'.vvp');compile_log=out/(name+'.compile.log')
        with compile_log.open('w')as f:subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(source)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
        result=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,timeout=120);log=out/(name+'.log');log.write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError(str(log))
        record=json.loads(next(l for l in result.stdout.splitlines()if l.startswith('{')));record.update(parameters=dict(zip(['SETS','LINE_BYTES','DEMAND_DEPTH','BUS_WIDTH','READ_WIDTH'],profile)),bench_sha256=sha(source),log_sha256=sha(log));records.append(record);print(json.dumps(record),flush=True)
    if any(sha(Path(p))!=h for p,h in manifest.items()):raise RuntimeError('验证期间源文件发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=manifest,profiles=records,checks=sum(r['checks']for r in records)),indent=2)+'\n')
if __name__=='__main__':main()
