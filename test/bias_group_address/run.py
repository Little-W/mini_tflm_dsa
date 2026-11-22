#!/usr/bin/env python3
"""验证偏置整组起始地址的完整模减法与分组借位四态语义。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CURRENT = Path('rtl/npu/top/npu_output_pipeline.sv')
WIDTHS = (1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 33, 47, 48, 63, 64)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def statements(text: str, *, reference: bool) -> str:
    start = text.index('assign is_bias_exec_m_ext =')
    end = text.index('wire [REG_WIDTH-1:0] is_bias_tail_rows_raw' if reference else
                     'assign is_bias_tail_rows_raw', start)
    text = text[start:end]
    mapping = {'REG_WIDTH': 'W', 'IS_BIAS_VALID_W': 'V', 'exec_m': 'i_exec_m',
               'is_bias_full_group_fallback': 'is_bias_full_group_base'} if reference else {
                   'p_reg_width': 'W', 'p_is_bias_valid_w': 'V'}
    for name, value in mapping.items():
        text = re.sub(r'\b' + name + r'\b', value, text)
    return re.sub(r'\(\*.*?\*\)', '', text, flags=re.S)


def tokens(text: str) -> str:
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S))


def execute(command: list[str], log: Path, *, timeout: int = 240) -> str:
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=timeout, check=True)
    return log.read_text()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-source', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {'reference': args.reference_source.resolve(),
             'current': args.source_root.resolve() / CURRENT}
    extracted = {name: statements(path.read_text(), reference=name == 'reference')
                 for name, path in paths.items()}
    if tokens(extracted['reference']) != tokens(extracted['current']):
        raise ValueError('分组借位语句的类型、运算及位选择必须保持相同')
    models = []
    for name, body in extracted.items():
        source = out / f'{name}.sv'
        source.write_text('`default_nettype none\n' +
            f'module bias_group_{name} #(parameter W=32, parameter V=10)(\n' +
            '    input wire [31:0] i_exec_m,\n' +
            '    input wire [V-1:0] i_group_rows_target,\n' +
            '    output wire [W-1:0] result, mask\n);\n' +
            '    localparam p_bias_count_bits=(V<W)?V:W;\n' +
            '    localparam p_bias_mask_groups=(p_bias_count_bits+3)/4;\n' +
            '    localparam p_bias_high_groups=(W-p_bias_count_bits+3)/4;\n' +
            '    wire [W-1:0] is_bias_exec_m_ext, is_bias_target_mask_ext;\n' +
            '    wire [W-1:0] is_bias_full_group_base;\n' +
            '    wire [W-1:0] is_bias_group_rows_target_ext=W\'(i_group_rows_target);\n' +
            '    wire [p_bias_count_bits:0] is_bias_low_difference;\n' +
            '    wire [p_bias_mask_groups-1:0] is_bias_mask_group_zero;\n' +
            '    wire [(p_bias_high_groups>0?p_bias_high_groups:1)-1:0] is_bias_high_group_zero;\n' +
            body + '\n    assign result=is_bias_full_group_base;\n' +
            '    assign mask=is_bias_target_mask_ext;\nendmodule\n`default_nettype wire\n')
        models.append(source)

    profiles = [(width, valid_width) for width in WIDTHS
                for valid_width in sorted({1, 4, 8, 10, max(1, width - 1), width, width + 1})]
    proof = ['module proof(input wire [31:0] exec_m, input wire [64:0] rows_target,',
             '    output wire correct);', f'wire [{2*len(profiles)-1}:0] correct_bits;']
    instances = []
    offset = 0
    for index, (width, valid_width) in enumerate(profiles):
        proof += [f'wire [{width-1}:0] result_{index}, mask_{index};',
                  f'bias_group_current #(.W({width}),.V({valid_width})) c_{index}(',
                  f' .i_exec_m(exec_m),.i_group_rows_target(rows_target[{valid_width-1}:0]),',
                  f' .result(result_{index}),.mask(mask_{index}));',
                  f"assign correct_bits[{2*index}] = (result_{index} == ({width}'(exec_m) - {width}'({valid_width}'(rows_target))));",
                  f"assign correct_bits[{2*index+1}] = (mask_{index} == ({width}'({valid_width}'(rows_target)) - {width}'(1)));" ]
        for name in paths:
            instances += [f'bias_group_{name} #(.W({width}),.V({valid_width})) {name}_{index}(',
                          f' .i_exec_m(exec_m),.i_group_rows_target(rows_target[{valid_width-1}:0]),',
                          f' .result({name}_bits[{offset} +: {width}]),',
                          f' .mask({name}_bits[{offset+width} +: {width}]));']
        offset += 2 * width
    proof += ['assign correct=&correct_bits;', 'endmodule']
    proof_source = out / 'proof.sv'
    proof_source.write_text('\n'.join(proof) + '\n')
    script, log = out / 'proof.ys', out / 'proof.log'
    script.write_text('read_slang --top proof ' + shlex.join(list(map(str, models + [proof_source]))) +
                      '\nprep -top proof -flatten\nopt_clean\ncheck -assert\n' +
                      'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
    text = execute([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--worker', str(script)], log)
    if 'SAT proof finished - no model found: SUCCESS!' not in text:
        raise RuntimeError('完整模减法证明未完成')
    print(f'BIAS_GROUP_FORMAL_PASS profiles={len(profiles)} input_bits=97', flush=True)

    bench = out / 'four_state.sv'
    bench.write_text('module four_state;\n' +
        '    reg [96:0] stimulus, known;\n' +
        '    wire [31:0] exec_m=stimulus[31:0];\n' +
        '    wire [64:0] rows_target=stimulus[96:32];\n' +
        f'    wire [{offset-1}:0] reference_bits,current_bits;\n' +
        '\n'.join(instances) + '''
    reg [31:0] random_state=32'h28c573fa;
    integer sample,bit_index,choice,checks=0,unknown_inputs=0,unknown_results=0;
    function automatic [31:0] step(input [31:0] value);
        reg [31:0] next_value;
        begin
            next_value=value^(value<<13);
            next_value=next_value^(next_value>>17);
            step=next_value^(next_value<<5);
        end
    endfunction
    task check;
        begin
            #1;
            checks=checks+1;
            if ((^stimulus)===1'bx) unknown_inputs=unknown_inputs+1;
            if ((^reference_bits)===1'bx) unknown_results=unknown_results+1;
            if(reference_bits!==current_bits)
                $fatal(1,"Bias group address differs at sample=%0d input=%h",checks,stimulus);
        end
    endtask
    initial begin
        for(sample=0;sample<32;sample=sample+1) begin
            for(bit_index=0;bit_index<97;bit_index=bit_index+1) begin
                random_state=step(random_state);known[bit_index]=random_state[0];
            end
            if(sample==0) known='0;
            if(sample==1) known='1;
            stimulus=known;check();
            for(bit_index=0;bit_index<97;bit_index=bit_index+1) begin
                stimulus=known;stimulus[bit_index]=1'bx;check();
                stimulus=known;stimulus[bit_index]=1'bz;check();
            end
            if(sample%8==7) $display("BIAS_GROUP_FOUR_STATE_PROGRESS systematic=%0d",sample+1);
        end
        for(sample=0;sample<5000;sample=sample+1) begin
            for(bit_index=0;bit_index<97;bit_index=bit_index+1) begin
                random_state=step(random_state);
                choice=sample<1000?int'(random_state[0]):int'(random_state[2:0]);
                case(choice)
                    2:stimulus[bit_index]=1'bx;
                    3:stimulus[bit_index]=1'bz;
                    default:stimulus[bit_index]=random_state[0];
                endcase
            end
            check();
            if(sample%1000==999) $display("BIAS_GROUP_FOUR_STATE_PROGRESS random=%0d",sample+1);
        end
        $display("BIAS_GROUP_FOUR_STATE_PASS samples=%0d unknown_inputs=%0d unknown_results=%0d",
                 checks,unknown_inputs,unknown_results);
        $finish;
    end
endmodule
''')
    binary, four_log = out / 'four_state.vvp', out / 'four_state.log'
    execute(['iverilog', '-g2012', '-s', 'four_state', '-o', str(binary),
             *map(str, models), str(bench)], out / 'four_state_build.log')
    text = execute(['vvp', str(binary)], four_log, timeout=1800)
    match = re.search(r'BIAS_GROUP_FOUR_STATE_PASS samples=(\d+) unknown_inputs=(\d+) unknown_results=(\d+)', text)
    if not match:
        raise RuntimeError('分组借位四态比较未完成')
    four = dict(zip(('samples', 'unknown_inputs', 'unknown_results'), map(int, match.groups())))
    report = {'passed': True, 'inputs_constrained': False, 'defined_input_bits': 97,
              'reference_grouped_statements_unchanged': True,
              'source_sha256': {str(path): digest(path) for path in paths.values()},
              'profiles': [{'reg_width': width, 'is_bias_valid_w': valid_width}
                           for width, valid_width in profiles],
              'formal': {'passed': True, 'profile_count': len(profiles), 'log_sha256': digest(log)},
              'four_state': {'passed': True, 'output_bits': offset,
                             'bit_comparisons': four['samples'] * offset, **four,
                             'log_sha256': digest(four_log)}}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['four_state']), flush=True)


if __name__ == '__main__':
    main()
