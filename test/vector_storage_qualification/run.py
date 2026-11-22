#!/usr/bin/env python3
"""检查共享存储读写资格的完整状态等价、四态行为和 RAM 数值访问。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

RELATIVE = Path('rtl/npu/buffers/vector_shared_store.sv')
PROFILES = [(size, banks, fixed) for size, banks in
            [(256, 6), (2048, 7), (2048, 8), (4096, 6), (4096, 9), (8192, 7)]
            for fixed in [0, 1]]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log, timeout=180):
    with log.open('w') as stream:
        result = subprocess.run(list(map(str, command)), stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(str(log))


def four_state_source(reference, current):
    ports = re.findall(r'    (input|output)  ?logic\s*(\[[^\]]+\])?\s*(\w+)\s*(\[\d+\])?[,\n]', reference)
    assert len(ports) == 37, len(ports)
    header = '''module comparison #(parameter p_bank_bytes=8192, p_total_bytes=57344,
 p_addr_width=$clog2(p_total_bytes/16), p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1),
 p_fixed_ps_channels=1)(input logic clk, input logic rst_n, input logic [31:0] sample,
 output integer comparisons=0);
 integer unsigned rng=32'h793ce518;
 function automatic [31:0] random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic sample_bit(input integer mixed);
  logic [31:0] value;
  value=random_word();
  if(mixed && value[3:0]==0)sample_bit=1'bx;
  else if(mixed && value[3:0]==1)sample_bit=1'bz;
  else sample_bit=value[8];
 endfunction
'''
    input_updates = []
    output_checks = []
    for direction, width, name, array in ports:
        if name in ['clk', 'rst_n']:
            continue
        declaration = f'{width or ""} {name} {array or ""}'
        if direction == 'input':
            header += 'reg ' + declaration + ';\n'
            statement = f'{name}'
            if array:
                count = int(array[1:-1])
                statement += '[item]'
            if width and 'data' in name:
                action = f'''for(integer word_index=0;word_index<$bits({statement})/32;word_index++)begin
 {statement}[word_index*32+:32]=random_word();
 if(sample%5==0)case(2'(random_word()))
  2'b00:{statement}[word_index*32+:32]='x;
  2'b01:{statement}[word_index*32+:32]='z;
 endcase
 end'''
            elif width:
                action = f'for(integer bit_index=0;bit_index<$bits({statement});bit_index++) {statement}[bit_index]=sample_bit(sample%5==0);'
            else:
                action = f'{statement}=sample_bit(sample%5==0);'
            if array:
                action = f'for(integer item=0;item<{count};item++)begin {action} end'
            input_updates.append(action)
        else:
            for label in ['reference', 'current']:
                header += f'wire {width or ""} {label}_{name} {array or ""};\n'
            if array:
                output_checks.append(f'for(integer item=0;item<{int(array[1:-1])};item++)begin if(reference_{name}[item]!==current_{name}[item])$fatal(1,"Shared storage output differs: {name}");comparisons++;end')
            else:
                output_checks.append(f'if(reference_{name}!==current_{name})$fatal(1,"Shared storage output differs: {name}");comparisons++;')
    for label in ['reference', 'current']:
        connections = [f'.{name}({name if direction=="input" else label+"_"+name})'
                       for direction, width, name, array in ports]
        header += f'''{label} #(.p_bank_bytes(p_bank_bytes),.p_total_bytes(p_total_bytes),
 .p_fixed_ps_channels(p_fixed_ps_channels)) u_{label} (
''' + ',\n'.join(connections) + ');\n'
    header += 'always @(negedge clk)begin\n' + '\n'.join(input_updates) + '''
 if(sample%13==0)begin i_cfg_valid=1;i_cfg_ia_banks=1;i_flush=0;i_enable=1;end
 if(sample%13==1)begin i_cfg_valid=0;i_flush=0;i_enable=1;end
 if(sample%17==0)begin i_weight_read_addr=i_weight_write_addr;i_weight_read_en=1;i_weight_write_en=1;i_weight_write_mask='1;end
 if(sample%19==0)begin i_ps_read_addr=i_ps_write_addr;i_ps_read_en=1;i_ps_write_en=1;end
 #1;
''' + '\n'.join(output_checks) + '\nend\n'
    header += 'always @(posedge clk)begin #1;\n' + '\n'.join(output_checks) + '\nend\nendmodule\n'
    header += 'module tb;reg clk=1,rst_n=0;reg [31:0] sample=0;integer count;\n'
    for index, (size, banks, fixed) in enumerate(PROFILES):
        header += f'wire integer c{index};comparison #(.p_bank_bytes({size}),.p_total_bytes({size*banks}),.p_fixed_ps_channels({fixed})) u{index}(clk,rst_n,sample,c{index});\n'
    header += '''initial begin
 for(sample=0;sample<4096;sample++)begin
  rst_n=(sample>1 && sample%127!=0);#2;clk=0;#2;clk=1;#2;
  if(sample%256==255)$display("Progress cycles=%0d",sample+1);
 end
 count=''' + '+'.join(f'c{i}' for i in range(len(PROFILES))) + ''';
 $display("VECTOR_STORAGE_FOUR_STATE_PASS comparisons=%0d profiles=12 cycles=4096",count);$finish;
end
endmodule
'''
    modules = []
    for label, source in [('reference', reference), ('current', current)]:
        # Icarus 使用等价的组合敏感表执行测试，RTL 条件、赋值和寄存边沿均保持相同。
        source = source.replace('module vector_shared_store #(', f'module {label} #(', 1)
        modules.append(source.replace('always_comb', 'always @*'))
    return '\n'.join(modules) + '\n' + header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--tool-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--reference', default='9d75f75a34b5d0d57fffe0eb6f7d5a29769308d6')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    tool_root = args.tool_root.resolve()
    reference = subprocess.check_output(['git', 'show', args.reference+':'+str(RELATIVE)], cwd=tool_root, text=True)
    current = (args.source_root/RELATIVE).read_text()
    for name, source in [('reference', reference), ('current', current)]:
        (out/(name+'.sv')).write_text(source)
    worker = [sys.executable, tool_root/'scripts/fpga/open_fpga_synth.py', '--worker']
    runs = []
    for size, banks, fixed in PROFILES:
        commands = []
        for label in ['reference', 'current']:
            commands += [shlex.join(['read_slang', '--top', 'vector_shared_store', f'-Gp_bank_bytes={size}',
                                     f'-Gp_total_bytes={size*banks}', f'-Gp_fixed_ps_channels={fixed}',
                                     str(out/(label+'.sv'))]),
                         'prep -top vector_shared_store -flatten', 'async2sync', 'opt -full',
                         f'rename vector_shared_store {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = out/f'formal_{size}_{banks}_{fixed}.ys'; script.write_text('\n'.join(commands)+'\n')
        log = script.with_suffix('.log'); execute(worker+[script], log)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        assert match and int(match[2]) == 0
        runs.append(dict(bank_bytes=size, banks=banks, fixed_ps_channels=fixed,
                         equivalent_bits=int(match[1]), passed=True, log_sha256=digest(log)))
        print(json.dumps(runs[-1]), flush=True)
    bench = out/'four_state.sv'; bench.write_text(four_state_source(reference, current))
    binary = out/'four_state.vvp'
    execute(['iverilog', '-g2012', '-s', 'tb', '-o', binary, bench], out/'four_state_compile.log')
    execute(['vvp', binary], out/'four_state.log', timeout=600)
    log_text = (out/'four_state.log').read_text()
    match = re.search(r'VECTOR_STORAGE_FOUR_STATE_PASS comparisons=(\d+)', log_text); assert match
    assert current == (args.source_root/RELATIVE).read_text()
    report = {'passed': True, 'reference_revision': args.reference,
              'source_sha256': digest(args.source_root/RELATIVE),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'test_sha256': digest(Path(__file__)), 'formal_input_constraints': None,
              'formal_profiles': runs, 'formal_equivalent_bits': sum(x['equivalent_bits'] for x in runs),
              'four_state_profiles': 12, 'four_state_cycles_per_profile': 4096,
              'four_state_comparisons': int(match[1]), 'four_state_log_sha256': digest(out/'four_state.log')}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='formal_profiles'}),flush=True)


if __name__ == '__main__':
    main()
