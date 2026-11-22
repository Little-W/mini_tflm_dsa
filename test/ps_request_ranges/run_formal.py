#!/usr/bin/env python3
"""验证实际帧请求资格表达式，并生成寄存器输入输出的独立测量模块。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/ps_compact/ps_frame_store.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text):
    marker = '    (* keep = "true" *) logic request_rows_'
    begin = text.index(marker if marker in text else '    wire request_valid=')
    end = text.index('    logic [RAW_LINEAR_BITS-3:0]', begin)
    return text[begin:end]


def model(name, expression, rows, frames):
    length = rows.bit_length()
    index = max(1, (frames-1).bit_length())
    width = 32 + index + 1 + frames + frames*length + length
    return f'''module {name}(input wire [{width-1}:0] stimulus,output wire valid);
 localparam integer MAX_FRAME_ROWS={rows},FRAME_COUNT={frames},LENGTH_BITS={length};
 wire [31:0] frame_rows;
 wire [{index-1}:0] frame_id;
 wire frame_init;
 wire [FRAME_COUNT-1:0] frame_valid;
 wire [LENGTH_BITS-1:0] frame_lengths[FRAME_COUNT];
 wire [FRAME_COUNT*LENGTH_BITS-1:0] packed_lengths;
 wire [LENGTH_BITS-1:0] directory_stride_q;
 assign {{frame_rows,frame_id,frame_init,frame_valid,packed_lengths,directory_stride_q}}=stimulus;
 for(genvar f=0;f<FRAME_COUNT;f++)begin:g_length
  assign frame_lengths[f]=packed_lengths[f*LENGTH_BITS+:LENGTH_BITS];
 end
 {expression}
 assign valid=request_valid;
endmodule
''', width


def bench(width):
    return f'''module tb;
 logic [{width-1}:0] stimulus=0,saved;
 wire reference_value,current_value;
 reference r(stimulus,reference_value);current c(stimulus,current_value);
 reg [31:0] rng=32'h8be32a79;
 integer checks=0,unknown_checks=0;
 task randomize;
  for(integer k=0;k<{width};k++)begin
   rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);stimulus[k]=rng[0];
  end
 endtask
 task check;
  #1;if(reference_value!==current_value)$fatal(1,"帧请求资格不同 input=%b reference=%b current=%b",stimulus,reference_value,current_value);
  checks++;
 endtask
 initial begin
  for(integer trial=0;trial<4096;trial++)begin randomize();check();end
  for(integer trial=0;trial<128;trial++)begin
   randomize();stimulus[{width-1}-:32]=32'(trial%64);saved=stimulus;check();
   for(integer k=0;k<{width};k++)begin
    stimulus=saved;stimulus[k]=1'bx;check();unknown_checks++;
    stimulus=saved;stimulus[k]=1'bz;check();unknown_checks++;
   end
  end
  stimulus='x;check();stimulus='z;check();
  $display("{{\\"passed\\":true,\\"checks\\":%0d,\\"unknown_checks\\":%0d}}",checks,unknown_checks);$finish;
 end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--profiles',nargs='+',default=['1:1','3:3','47:16','512:16','1024:32'])
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources={'reference':args.reference_root/RTL,'current':args.source_root/RTL}
    hashes={str(p):digest(p)for p in [*sources.values(),Path(__file__).resolve()]};records=[]
    unchanged=[read_rtl_text(p).replace(extract(read_rtl_text(p)),'<request_qualification>')for p in sources.values()]
    if unchanged[0]!=unchanged[1]:raise RuntimeError('请求资格以外的设计内容不同')
    for profile in args.profiles:
        rows,frames=map(int,profile.split(':'));directory=out/profile.replace(':','_');directory.mkdir(exist_ok=True)
        modules=[]
        for name,path in sources.items():
            text,width=model(name,extract(read_rtl_text(path)),rows,frames);modules.append(text)
            folder=out/(name+'_source')/profile.replace(':','_')/'test/ps_request';folder.mkdir(parents=True,exist_ok=True)
            (folder/'qualification.sv').write_text(text.replace('module '+name+'(', 'module qualification(')+f'''
module ps_request_measure(input wire clk,input wire [{width-1}:0] stimulus,output logic valid);
 logic [{width-1}:0] sampled;
 wire combinational_value;
 always_ff @(posedge clk)begin sampled<=stimulus;valid<=combinational_value;end
 qualification dut(sampled,combinational_value);
endmodule
''')
        expression=directory/'models.sv';expression.write_text('\n'.join(modules)+f'''
module formal(input wire [{width-1}:0] stimulus,output wire equivalent);
 wire a,b;reference r(stimulus,a);current c(stimulus,b);assign equivalent=a==b;
endmodule
''')
        script=directory/'prove.ys';script.write_text(f'read_slang --top formal {shlex.quote(str(expression))}\nprep -top formal -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        log=directory/'formal.log'
        with log.open('w')as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=90)
        simulation=directory/'four_state.sv';simulation.write_text('\n'.join(modules)+bench(width));binary=directory/'sim.vvp'
        with (directory/'compile.log').open('w')as stream:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(simulation)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=60)
        result=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,timeout=60)
        (directory/'simulation.log').write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError(str(directory/'simulation.log'))
        row=json.loads(next(line for line in result.stdout.splitlines()if line.startswith('{')))
        row.update(MAX_FRAME_ROWS=rows,FRAME_COUNT=frames,input_bits=width,formal_log_sha256=digest(log),simulation_log_sha256=digest(directory/'simulation.log'))
        records.append(row);print(json.dumps(row),flush=True)
    if any(digest(Path(p))!=h for p,h in hashes.items()):raise RuntimeError('验证期间源文件发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,inputs_constrained=False,unchanged_outside_request_qualification=True,profiles=records),indent=2)+'\n')


if __name__=='__main__':main()
