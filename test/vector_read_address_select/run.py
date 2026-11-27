#!/usr/bin/env python3
"""检查生产地址来源选择的全部输出、读取优先级和四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine_address.sv')
REFERENCE = '7c6599e002c9abb8906b73554c65a74b0fe8d780'
FIELDS = [('state', 6), ('load_kind', 3), ('i_load_read_select', 6),
          ('i_state_soft_lut_read', 1), ('i_state_pool_read', 1),
          ('rhs_base', 32), ('input_base', 32), ('bias_base', 32),
          ('multiplier_base', 32), ('shift_base', 32), ('vector_s16', 1),
          ('channel_base', 16), ('vector_offset', 32),
          ('pool_byte_offset', 32), ('soft_lut_index_q', 8)]
WIDTH = sum(width for _, width in FIELDS)
MODES = [('generic', []), ('synthesis', ['-DSYNTHESIS=1']),
         ('fpga', ['-DXILINX_FPGA=1']),
         ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=300)


def model(name, text):
    if 'vector_read_address_select u_read_select' in text:
        first = text.index("  always_comb begin\n    read_select_i_load_base = 32'd0;")
        private = '''  logic [31:0] read_select_i_load_base, read_select_i_load_offset;
  logic read_select_i_lut_read, read_select_i_pool_read;
'''
    else:
        first = text.index("  always_comb begin\n    read_address_base = 32'd0;")
        private = ''
    last = text.index('  vector_read_address_add u_read_address', first)
    declarations = '\n'.join(f'  logic [{width-1}:0] {field};' for field, width in FIELDS)
    return f'''// 直接使用生产模块中的地址候选准备和来源选择过程。
module {name} #(parameter bit p_registered_read_phase = 1'b1)(
  input logic [{WIDTH-1}:0] i_stimulus, // 全部地址数据与控制输入
  output logic [79:0] o_result // 完整基址、偏移及通道分量
);
{declarations}
  typedef struct packed {{
    logic [31:0] rhs_base, input_base, bias_base, multiplier_base, shift_base;
    logic vector_s16;
  }} cfg_t;
  cfg_t c;
  logic [31:0] read_address_base, read_address_offset;
  logic [15:0] read_address_channel;
{private}
  assign {{{','.join(field for field, _ in FIELDS)}}} = i_stimulus;
  assign c = {{rhs_base, input_base, bias_base, multiplier_base, shift_base, vector_s16}};
{text[first:last]}
  assign o_result = {{read_address_base, read_address_offset, read_address_channel}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'show', REFERENCE+':'+str(SOURCE)],
                                       cwd=ROOT, text=True)
    models = out/'models.sv'
    models.write_text(model('reference_choice', original) +
                      model('candidate_choice', (ROOT/SOURCE).read_text()))
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([models], ROOT)
    source_hashes = {str(path.relative_to(ROOT)): digest(path)
                     for path in sources if path.is_relative_to(ROOT)}
    source_hashes[str(SOURCE)] = digest(ROOT/SOURCE)
    positions = {}
    position = WIDTH
    for field, width in FIELDS:
        position -= width
        positions[field] = position
    bench = out/'tb.sv'
    bench.write_text(f'''`timescale 1ns/1ps
// 两种读取资格配置使用相同输入，覆盖独立资格、任意类型编码和未知数据位。
module tb;
  logic [{WIDTH-1}:0] i_stimulus;
  wire [79:0] expected [2], actual [2];
  integer seed = 261127;
  integer comparisons = 0;
  for (genvar registered = 0; registered < 2; registered++) begin : g_mode
    reference_choice #(.p_registered_read_phase(registered)) u_reference (
      .i_stimulus(i_stimulus), .o_result(expected[registered]));
    candidate_choice #(.p_registered_read_phase(registered)) u_candidate (
      .i_stimulus(i_stimulus), .o_result(actual[registered]));
  end
  function automatic logic four(input integer value);
    case (value & 3)
      0: four=1'b0; 1: four=1'b1; 2: four=1'bx; 3: four=1'bz;
    endcase
  endfunction
  initial begin
    for (integer sample=0; sample<262144; sample=sample+1) begin
      i_stimulus={{{','.join(['$random(seed)']*((WIDTH+31)//32))}}};
      i_stimulus[{positions['state']} +: 6] = 6'(sample);
      i_stimulus[{positions['i_state_soft_lut_read']}] = four(sample);
      i_stimulus[{positions['i_state_pool_read']}] = four(sample>>2);
      case (sample%8)
        0: i_stimulus[sample%{WIDTH}]=1'bx;
        1: i_stimulus[sample%{WIDTH}]=1'bz;
        2: i_stimulus[{positions['rhs_base']} +: 32]='z;
        3: i_stimulus[{positions['pool_byte_offset']} +: 32]='z;
        4: i_stimulus[{positions['channel_base']} +: 16]='x;
        5: i_stimulus[{positions['state']} +: 6]='x;
        6: i_stimulus[{positions['i_load_read_select']} +: 6]='z;
        default: begin end
      endcase
      #1;
      for (integer registered=0; registered<2; registered=registered+1) begin
        if (actual[registered] !== expected[registered])
          $fatal(1,"地址来源不一致 sample=%0d registered=%0d",sample,registered);
        comparisons=comparisons+1;
      end
    end
    $display("READ_SELECT_PASS comparisons=%0d",comparisons);
    $finish;
  end
endmodule
''')
    formal, four_state = [], []
    for mode, flags in MODES:
        for registered in (0, 1):
            commands = []
            for label in ('reference', 'candidate'):
                top = label+'_choice'
                commands += ['read_slang --top '+top+' '+shlex.join(
                    [*flags, f'-Gp_registered_read_phase={registered}', *map(str, sources)]),
                    'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                    'prep -top '+top+' -flatten', 'opt -full', 'rename -top '+label,
                    'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate proof', 'hierarchy -top proof',
                         'equiv_simple', 'equiv_status -assert']
            script = out/f'{mode}_registered{registered}.ys'
            script.write_text('\n'.join(commands)+'\n')
            log = script.with_suffix('.log')
            execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            formal.append(dict(mode=mode, registered_read_phase=registered,
                               passed=True, log_sha256=digest(log)))
        binary = out/(mode+'.vvp')
        execute(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', binary, *sources, bench],
                out/(mode+'_compile.log'))
        log = out/(mode+'_four_state.log')
        execute(['vvp', binary], log)
        assert 'READ_SELECT_PASS comparisons=524288' in log.read_text()
        four_state.append(dict(mode=mode, comparisons=524288, log_sha256=digest(log)))
        print(mode+' PASS', flush=True)
    assert all(digest(ROOT/path)==value for path, value in source_hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True, reference_revision=REFERENCE,
        compared_output_bits=80, input_assumptions=[], source_sha256=source_hashes,
        formal=formal, four_state=four_state), ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
