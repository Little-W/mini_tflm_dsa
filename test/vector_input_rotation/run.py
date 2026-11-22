#!/usr/bin/env python3
"""验证向量输入循环选择的数值、四态行为及映射资源。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import run_stage
from netlist_metrics import analyze


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fragment(source):
    start = source.index('  if (p_input_bank_storage) begin : g_spatial_input_data')
    end = source.index('  assign q_clamped_data', start)
    return source[start:end]


def wrapper(name, body):
    return f'''module {name} (
    input logic clk, pool_response_fire, window_response_fire, global_pool,
    input logic [2:0] pool_first_bank, window_first_bank,
    input logic [127:0] dma_words, window_words,
    output logic [127:0] selected_window
);
    localparam bit p_input_bank_storage=1'b1;
    localparam int INPUT_BANKS=8;
    localparam int WINDOW_BANK_W=3;
    wire signed [15:0] rd_data[8], win_rsp_data[8];
    wire signed [15:0] window_bank_data[8], pool_bank_data[8];
    for (genvar lane=0;lane<8;lane++) begin : g_port
        assign rd_data[lane]=dma_words[16*lane+:16];
        assign win_rsp_data[lane]=window_words[16*lane+:16];
        always_ff @(posedge clk) begin
            selected_window[16*lane+:16] <= window_bank_data[lane];
        end
    end
{body}
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--measure',action='store_true')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    roots={'reference':args.reference_root.resolve(),'current':args.source_root.resolve()}
    hashes={label:sha(root/SOURCE) for label,root in roots.items()}
    files={}
    for label,root in roots.items():
        path=out/(label+'.sv');path.write_text(wrapper('rotation_'+label,fragment((root/SOURCE).read_text())))
        files[label]=path
    env=dict(os.environ)
    formal=out/'equivalence.ys'
    formal.write_text(f'''read_slang --top rotation_reference {files['reference']}
prep -top rotation_reference -flatten
memory_map
opt_clean
rename rotation_reference gold
design -stash reference
read_slang --top rotation_current {files['current']}
prep -top rotation_current -flatten
memory_map
opt_clean
rename rotation_current gate
design -copy-from reference -as gold gold
equiv_make gold gate proof
hierarchy -top proof
equiv_simple -seq 2
equiv_induct -seq 3
equiv_status -assert
''')
    formal_result=run_stage(formal,out/'equivalence.log',env)
    tb=out/'tb.sv'
    tb.write_text('''module tb;
  reg clk=0, pool_response_fire, window_response_fire, global_pool;
  reg [2:0] pool_first_bank, window_first_bank;
  reg [127:0] dma_words,window_words;
  wire [127:0] old_window,new_window;
  integer checks=0,seed=32'h627541ac;
  rotation_reference u_reference(.clk(clk),.pool_response_fire(pool_response_fire),
    .window_response_fire(window_response_fire),.global_pool(global_pool),
    .pool_first_bank(pool_first_bank),.window_first_bank(window_first_bank),
    .dma_words(dma_words),.window_words(window_words),
    .selected_window(old_window));
  rotation_current u_current(.clk(clk),.pool_response_fire(pool_response_fire),
    .window_response_fire(window_response_fire),.global_pool(global_pool),
    .pool_first_bank(pool_first_bank),.window_first_bank(window_first_bank),
    .dma_words(dma_words),.window_words(window_words),
    .selected_window(new_window));
  function automatic state_bit(input integer code);
    case(code)
      0:state_bit=1'b0;
      1:state_bit=1'b1;
      2:state_bit=1'bx;
      3:state_bit=1'bz;
    endcase
  endfunction
  task check;
    begin
      #1;clk=1;#1;
      if (old_window!==new_window)
        $fatal(1,"rotation mismatch check=%0d first=%b old=%h current=%h",
          checks,window_first_bank,old_window,new_window);
      checks=checks+1;clk=0;#1;
    end
  endtask
  initial begin
    for(integer sample=0;sample<64;sample++)begin
      for(integer choice=0;choice<64;choice++)begin
        for(integer bit_i=0;bit_i<3;bit_i++)begin
          window_first_bank[bit_i]=state_bit((choice>>(2*bit_i))&3);
          pool_first_bank[bit_i]=state_bit(((63-choice)>>(2*bit_i))&3);
        end
        for(integer mode=0;mode<4;mode++)begin
          global_pool=state_bit(mode);
          for(integer event_i=0;event_i<4;event_i++)begin
            dma_words={$random(seed),$random(seed),$random(seed),$random(seed)};
            window_words={$random(seed),$random(seed),$random(seed),$random(seed)};
            if (sample%4==0)begin
              dma_words[sample*2]=1'bx;
              window_words[127-sample*2]=1'bz;
            end
            pool_response_fire=state_bit(event_i);
            window_response_fire=state_bit((event_i+1)%4);
            check();
          end
        end
      end
    end
    repeat(2)check();
    $display("VECTOR_ROTATION_PASS checks=%0d",checks);
    $finish;
  end
endmodule
''')
    executable=out/'simulation.vvp'
    build=['iverilog','-g2012','-s','tb','-o',str(executable),*map(str,files.values()),str(tb)]
    with (out/'build.log').open('w') as stream:
        subprocess.run(build,stdout=stream,stderr=subprocess.STDOUT,check=True)
    result=subprocess.run(['vvp',str(executable)],capture_output=True,text=True,timeout=180)
    (out/'simulation.log').write_text(result.stdout+result.stderr)
    match=re.search(r'VECTOR_ROTATION_PASS checks=(\d+)',result.stdout)
    if result.returncode or not match:raise RuntimeError(result.stdout+result.stderr)
    measurements={}
    if args.measure:
        for label,path in files.items():
            top='rotation_'+label;folder=out/label;folder.mkdir(exist_ok=True)
            script=folder/'synthesis.ys'
            script.write_text(f'''read_slang --top {top} {path}
synth_xilinx -top {top} -family xc7 -abc9 -flatten -noiopad -noclkbuf
check -assert
write_json {folder/'mapped.json'}
''')
            stage=run_stage(script,folder/'synthesis.log',env)
            module=json.loads((folder/'mapped.json').read_text())['modules'][top]
            metrics=analyze(module)
            (folder/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
            measurements[label]={'resources':metrics['resources'],
                'longest_register_path_cells':metrics['paths']['longest_register_path_cells'],'stage':stage}
    assert hashes=={label:sha(root/SOURCE) for label,root in roots.items()}
    summary={'passed':True,'strict_four_state_equivalence':True,'four_state_checks':int(match[1]),
        'parameters':{'INPUT_BANKS':8,'WINDOW_BANK_W':3,'data_bits_per_bank':16},
        'source_sha256':hashes,'formal':formal_result,'measurements':measurements,
        'scope':'实际 RTL 输入保存和循环选择，输出另设同周期比较寄存器；完整引擎回归另行执行。'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
