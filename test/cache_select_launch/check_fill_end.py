#!/usr/bin/env python3
"""比较生产填充边界计算的完整位向量及未知输入传播。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/cache/conv_windowed_cache.sv'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module(text, name):
    first = text.index('  for (genvar fill_mode=0; fill_mode<2; fill_mode++)')
    last = text.index('  assign ram_wen=', first)
    return f'''module {name} #(parameter integer LINE_BYTES=128, READ_WIDTH=64)(
  input logic [31:0] select_addr, demand_addr, end_q,
  input logic bypass_q,
  output logic [95:0] observed);
  localparam integer LB=$clog2(LINE_BYTES);
  localparam integer p_read_bytes=READ_WIDTH/8;
  localparam integer p_read_shift=$clog2(p_read_bytes);
  logic [31:0] fill_candidate_end;
  logic [1:0][31:0] fill_end_candidates;
{text[first:last]}
  assign observed={{fill_candidate_end,fill_end_candidates}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3b1c0c5b664d28397dcb257ad8b9cbadea730b6b')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    old = subprocess.check_output(['git', 'show', args.reference + ':' + SOURCE], cwd=ROOT).decode()
    current = (ROOT / SOURCE).read_text()
    models = out / 'models.sv'
    models.write_text(module(old, 'reference_end') + module(current, 'current_end'))
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([models], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    results = []
    for line_bytes, read_width in ((8,32), (16,32), (32,64), (128,64), (128,128)):
        instances = f'''
  wire [31:0] select_addr=stimulus[31:0];
  wire [31:0] demand_addr=stimulus[63:32];
  wire [31:0] end_q=stimulus[95:64];
  wire bypass_q=stimulus[96];
  reference_end #(.LINE_BYTES({line_bytes}),.READ_WIDTH({read_width})) old(
    .select_addr(select_addr),.demand_addr(demand_addr),.end_q(end_q),.bypass_q(bypass_q),.observed(expected));
  current_end #(.LINE_BYTES({line_bytes}),.READ_WIDTH({read_width})) dut(
    .select_addr(select_addr),.demand_addr(demand_addr),.end_q(end_q),.bypass_q(bypass_q),.observed(actual));
'''
        for mode, flags in (('generic',['-USYNTHESIS','-UXILINX_FPGA']),
                            ('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])):
            label = f'{mode}_{line_bytes}_{read_width}'
            proof = out / (label + '_proof.sv')
            proof.write_text('module proof(input logic [96:0] stimulus, output wire [95:0] actual);\n'
                '  wire [95:0] expected;\n' + instances +
                '  always_comb assert(actual == expected);\nendmodule\n')
            script = out / (label + '.ys')
            script.write_text('read_slang --top proof ' + shlex.join(flags + list(map(str, sources + [proof]))) + '\n'
                'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                'prep -top proof -flatten\nchformal -lower\n'
                'sat -verify -prove-asserts -show-inputs\n')
            log = out / (label + '_formal.log')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            assert 'SUCCESS' in log.read_text()
            bench = out / (label + '_tb.sv')
            bench.write_text('module tb;\n  logic [96:0] stimulus;\n  wire [95:0] expected,actual;\n'
                '  integer checks=0; integer seed=32\'h63c89154;\n' + instances + '''
  function automatic logic value4(input integer value);
    case (value&3)
      0:value4=1'b0; 1:value4=1'b1; 2:value4=1'bx; 3:value4=1'bz;
    endcase
  endfunction
  task automatic compare;
    #1;
    if (actual !== expected)
      $fatal(1,"fill end check=%0d stimulus=%h expected=%h actual=%h",checks,stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    if ($bits(stimulus) != 97 || $bits(actual) != 96) $fatal(1,"width");
    // 全部地址位均覆盖零值、最大值、逐位边界以及 X、Z 输入。
    for (integer bit_index=0; bit_index<97; bit_index++) begin
      for (integer control=0; control<4; control++) begin
        for (integer unknown=2; unknown<4; unknown++) begin
          stimulus='0; stimulus[96]=value4(control);
          stimulus[bit_index]=value4(unknown); compare();
          stimulus='1; stimulus[96]=value4(control);
          stimulus[bit_index]=value4(unknown); compare();
        end
      end
    end
    for (integer trial=0; trial<16384; trial++) begin
      stimulus={$random(seed),$random(seed),$random(seed),1'b0};
      stimulus[96]=value4(trial);
      case(trial%4)
        0: stimulus[95:64]=stimulus[31:0];
        1: stimulus[95:64]=stimulus[31:0]+1;
        2: stimulus[95:64]=stimulus[63:32]+1;
        3: begin end
      endcase
      if (trial%3)
        for(integer index=0;index<3;index++) stimulus[(trial+index*31)%96]=value4($random(seed));
      compare();
    end
    $display("FILL_END_PASS checks=%0d",checks); $finish;
  end
endmodule
''')
            binary = out / (label + '.vvp')
            simulation_flags = [flag for flag in flags if not flag.startswith('-U')]
            build = subprocess.run([shutil.which('iverilog') or 'iverilog','-g2012','-s','tb',
                *simulation_flags,'-o',str(binary),*map(str,sources),str(bench)], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,text=True,timeout=120)
            (out / (label + '_build.log')).write_text(build.stdout)
            build.check_returncode()
            simulation = subprocess.run([shutil.which('vvp') or 'vvp',str(binary)],
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True,timeout=180)
            simulation_log = out / (label + '_four_state.log'); simulation_log.write_text(simulation.stdout)
            checks = re.search(r'FILL_END_PASS checks=(\d+)',simulation.stdout); assert checks
            row = dict(mode=mode,line_bytes=line_bytes,read_width=read_width,passed=True,
                four_state_checks=int(checks[1]),compared_output_bits=96,input_constraints=[],
                formal_log_sha256=digest(log),simulation_log_sha256=digest(simulation_log))
            results.append(row);print(json.dumps(row),flush=True)
    assert all(digest(path)==expected for path,expected in hashes.items())
    assert (ROOT / SOURCE).read_text()==current
    (out / 'summary.json').write_text(json.dumps(dict(passed=True,reference_commit=args.reference,
        controller_sha256=digest(ROOT / SOURCE),source_sha256=hashes,runner_sha256=digest(__file__),
        results=results,four_state_checks=sum(row['four_state_checks'] for row in results)),indent=2)+'\n')


if __name__ == '__main__':
    main()
