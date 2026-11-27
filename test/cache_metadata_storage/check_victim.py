#!/usr/bin/env python3
"""检查缓存替换冲突资格的任意输入等价及四态分配律。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')
QUALIFICATION = Path('rtl/npu/dma/cache/conv_cache_victim_qualification.sv')
PORTS = '''
  input logic [1:0] fg_state, // 当前前台状态
  input logic demand_lookup_ready, // 需求查询已经完成
  input logic bypass_q, // 当前采用缓存旁路
  input logic demand_filled, // 旁路需求已经填充
  input logic [SI-1:0] select_set, // 替换项的缓存组号
  input logic [SI-1:0] demand_set, // 当前需求的缓存组号
  input logic [SI-1:0] demand_fill_set, // 旁路填充的缓存组号
  input logic [WI-1:0] select_way, // 替换项的缓存路号
  input logic [WI-1:0] demand_fill_way, // 旁路填充的缓存路号
  input logic [WAYS-1:0] demand_selected_victim // 被选择缓存路的命中结果
'''
NAMES = ('fg_state', 'demand_lookup_ready', 'bypass_q', 'demand_filled',
         'select_set', 'demand_set', 'demand_fill_set', 'select_way',
         'demand_fill_way', 'demand_selected_victim')
MODES = (('generic', ['-USYNTHESIS', '-UXILINX_FPGA']),
         ('synthesis', ['-DSYNTHESIS=1', '-UXILINX_FPGA']),
         ('fpga', ['-USYNTHESIS', '-DXILINX_FPGA=1']),
         ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(name, text):
    first = text.index('  logic demand_victim_eligible, bypass_victim_eligible, victim_conflict_parallel;')
    last = text.index('  always_comb begin\n    select_victim_conflict =', first)
    state = re.search(r'typedef enum logic \[1:0\] \{FG_IDLE,.*?fg_state_t;', text).group(0)
    return f'''// 从完整缓存直接提取替换冲突的组合过程。
module {name} #(parameter integer WAYS=2,SI=4,WI=WAYS<=1?1:$clog2(WAYS))(
{PORTS}, output logic o_conflict // 当前需求与替换项发生冲突
);
{state}
{text[first:last]}
assign o_conflict=victim_conflict_parallel;
endmodule
'''


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='9e3e5d6a6f47befe6c86aceacad7999923206458')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', args.reference + ':' + str(SOURCE)], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    source_hash = digest(ROOT / SOURCE)
    models = out / 'models.sv'
    models.write_text(model('reference', reference).replace(
        'conv_cache_victim_qualification', 'reference_victim_qualification') + model('current', current))
    reference_qualification = out / 'reference_victim_qualification.sv'
    reference_qualification.write_text(subprocess.check_output(
        ['git', 'show', args.reference + ':' + str(QUALIFICATION)], cwd=ROOT, text=True).replace(
            'module conv_cache_victim_qualification', 'module reference_victim_qualification', 1))
    connections = ','.join('.' + name + '(' + name + ')' for name in NAMES)
    proof = out / 'proof.sv'
    proof.write_text(f'''// 所有输入均可独立变化，不限制状态、地址或命中组合。
module proof #(parameter integer WAYS=2,SI=4,WI=WAYS<=1?1:$clog2(WAYS))(
{PORTS}, output logic equivalent // 两种冲突结果完全一致
);
wire a,b;
reference #(.WAYS(WAYS),.SI(SI)) u_reference({connections},.o_conflict(a));
current #(.WAYS(WAYS),.SI(SI)) u_current({connections},.o_conflict(b));
assign equivalent=a===b;
endmodule
''')
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([models, proof, reference_qualification], ROOT)
    dependency_hashes = {str(path.relative_to(ROOT)): digest(path)
                         for path in sources if path.is_relative_to(ROOT)}
    records = []
    for mode, flags in MODES:
        for sets, ways in ((2, 1), (16, 2), (256, 2)):
            name = f'{mode}_sets{sets}_ways{ways}'
            script = out / (name + '.ys')
            script.write_text('read_slang --top proof ' + shlex.join(
                flags + [f'-GSI={sets.bit_length()-1}', f'-GWAYS={ways}'] + list(map(str, sources))) +
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy'
                '\nprep -top proof -flatten\nopt -full\nsat -verify -prove equivalent 1 -show-inputs\n')
            log = out / (name + '.log')
            execute([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            assert 'SUCCESS!' in log.read_text()
            records.append({'mode': mode, 'sets': sets, 'ways': ways,
                            'passed': True, 'log_sha256': digest(log)})
    bench = out / 'tb.sv'
    declarations = '\n'.join(
        declaration.replace('input logic', 'logic').rstrip().rstrip(',') + '; // ' + comment
        for line in PORTS.splitlines() if line.strip()
        for declaration, comment in [line.split('//', 1)]) + '\n'
    bench.write_text('''`timescale 1ns/1ps
// 穷举状态、资格、命中的四态值，以及各地址关系的真、假、未知结果。
module tb;
localparam integer WAYS=2,SI=4,WI=1;
''' + declarations + f'''
wire a,b;
integer checks=0;
reference u_reference({connections},.o_conflict(a));
current u_current({connections},.o_conflict(b));
function automatic logic four(input integer code);
 case(code&3)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
endfunction
initial begin
 select_set='0;select_way='0;
 for(integer state_code=0;state_code<16;state_code++)begin
  fg_state={{four(state_code>>2),four(state_code)}};
  for(integer flags=0;flags<64;flags++)begin
   demand_lookup_ready=four(flags);bypass_q=four(flags>>2);demand_filled=four(flags>>4);
   for(integer hits=0;hits<16;hits++)begin
    demand_selected_victim={{four(hits>>2),four(hits)}};
    for(integer relations=0;relations<27;relations++)begin
     case(relations%3)0:demand_set='0;1:demand_set=1;2:demand_set='x;endcase
     case((relations/3)%3)0:demand_fill_set='0;1:demand_fill_set=1;2:demand_fill_set='x;endcase
     case((relations/9)%3)0:demand_fill_way='0;1:demand_fill_way=1;2:demand_fill_way='x;endcase
     #1;if(a!==b)$fatal(1,"replacement conflict differs state=%b flags=%0d relation=%0d",fg_state,flags,relations);
     checks++;
    end
   end
  end
 end
 $display("VICTIM_QUALIFICATION_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    four_state = []
    for mode, flags in MODES:
        binary = out / (mode + '.vvp')
        execute(['iverilog', '-g2012', '-s', 'tb', *[f for f in flags if f.startswith('-D')],
                 '-o', binary, *sources, bench], out / (mode + '_compile.log'))
        log = out / (mode + '_four_state.log')
        execute(['vvp', binary], log)
        assert 'VICTIM_QUALIFICATION_PASS checks=442368' in log.read_text()
        four_state.append({'mode': mode, 'passed': True, 'comparisons': 442368,
                           'log_sha256': digest(log)})
    assert digest(ROOT / SOURCE) == source_hash
    assert all(digest(ROOT / path) == expected for path, expected in dependency_hashes.items())
    (out / 'summary.json').write_text(json.dumps({
        'passed': True, 'reference_commit': args.reference, 'input_constraints': [],
        'formal': records, 'four_state': four_state, 'source_sha256': source_hash,
        'dependency_sha256': dependency_hashes,
        'runner_sha256': digest(__file__),
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
