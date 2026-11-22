#!/usr/bin/env python3
"""证明实际偏置驻留表达式的完整输入关系，并严格比较四态结果。"""
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
SOURCE = Path('rtl/npu/loaders/bias_loader_buffer.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')
WIDTHS = (1, 2, 3, 8, 12, 28, 29, 32)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def region(source: str) -> str:
    start = source.index('  assign load_request_idx =')
    end = source.index('  assign resident_current', start)
    return source[start:end]


def surroundings(source: str) -> str:
    source = source.replace(region(source), 'RESIDENCY_EXPRESSIONS')
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    return re.sub(r'\s+', '', source)


def execute(command: list[str], log: Path) -> str:
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=240)
    return log.read_text()


PORTS = '''
    input wire [W-1:0] load_block_idx, current_block_idx, group_blocks_needed,
    input wire [1:0][W-1:0] bank_block_idx,
    input wire [1:0][W:0] bank_end_q,
    input wire [1:0] bank_loaded,
'''
CONNECTIONS = '''.load_block_idx(load_block_idx), .current_block_idx(current_block_idx),
    .group_blocks_needed(group_blocks_needed), .bank_block_idx(bank_block_idx),
    .bank_end_q(bank_end_q), .bank_loaded(bank_loaded)'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--configurations', nargs='+', choices=('generic', 'asic', 'fpga'),
                        default=('generic', 'asic', 'fpga'))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    texts = {label: (root / SOURCE).read_text() for label, root in roots.items()}
    if surroundings(texts['reference']) != surroundings(texts['current']):
        raise ValueError('驻留表达式之外的缓冲区逻辑必须完全相同')
    models = []
    for label, root in roots.items():
        (out / (label + '_source.sv')).write_text(texts[label])
        helper = out / (label + '_helper.sv')
        helper.write_text((root / HELPER).read_text().replace(
            'parallel_prefix_add', label + '_parallel_prefix_add'))
        model = out / (label + '.sv')
        model.write_text('`default_nettype none\n' +
            f'module range_{label} #(parameter W=29, parameter SHARE=0)(\n' + PORTS +
            '    output wire [7:0] result\n);\n' +
            '  localparam CNT_W=W, RANGE_WIDTH=W+1, p_share_load_index=SHARE;\n' +
            '  wire [W-1:0] load_request_idx;\n' +
            '  wire [1:0][1:0] window_end_valid;\n' +
            '  wire [1:0] load_window_hit, current_window_hit;\n' +
            region(texts[label]).replace('parallel_prefix_add', label + '_parallel_prefix_add') +
            '  assign result={window_end_valid,load_window_hit,current_window_hit};\n' +
            'endmodule\n`default_nettype wire\n')
        models.extend([model, helper])

    miter = out / 'proof.sv'
    miter.write_text('module proof #(parameter W=29, parameter SHARE=0)(\n' + PORTS +
        '    output wire correct\n);\n  wire [7:0] a,b;\n' +
        f'  range_reference #(.W(W),.SHARE(SHARE)) r({CONNECTIONS},.result(a));\n' +
        f'  range_current #(.W(W),.SHARE(SHARE)) c({CONNECTIONS},.result(b));\n' +
        '  assign correct=(a==b);\nendmodule\n')
    bench = out / 'four_state.sv'
    bench.write_text('''module four_state;
    parameter W=29;
    localparam BITS=7*W+4;
    reg [BITS-1:0] stimulus, known;
    wire [W-1:0] load_block_idx,current_block_idx,group_blocks_needed;
    wire [1:0][W-1:0] bank_block_idx;
    wire [1:0][W:0] bank_end_q;
    wire [1:0] bank_loaded;
    wire [15:0] a,b;
    assign {bank_loaded,bank_end_q,bank_block_idx,group_blocks_needed,
            current_block_idx,load_block_idx}=stimulus;
''' + '\n'.join(
        f'    range_{label} #(.W(W),.SHARE({share})) {label}_{share}' +
        f'({CONNECTIONS},.result({result}[{share*8}+:8]));'
        for label, result in [('reference', 'a'), ('current', 'b')] for share in [0, 1]) + '''
    reg [31:0] random_state=32'h793fea25;
    integer sample,bit_index,choice,checks=0,unknown_results=0,unknown_inputs=0;
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
            if ((^a)===1'bx) unknown_results=unknown_results+1;
            if(a!==b) $fatal(1,"Bias residency differs input=%h old=%b current=%b",stimulus,a,b);
        end
    endtask
    initial begin
        for(sample=0;sample<64;sample=sample+1) begin
            for(bit_index=0;bit_index<BITS;bit_index=bit_index+1) begin
                random_state=step(random_state);
                known[bit_index]=random_state[0];
            end
            if(sample==0) known='0;
            if(sample==1) known='1;
            stimulus=known;check();
            for(bit_index=0;bit_index<BITS;bit_index=bit_index+1) begin
                stimulus=known;stimulus[bit_index]=1'bx;check();
                stimulus=known;stimulus[bit_index]=1'bz;check();
            end
        end
        for(sample=0;sample<20000;sample=sample+1) begin
            for(bit_index=0;bit_index<BITS;bit_index=bit_index+1) begin
                random_state=step(random_state);
                choice=sample<5000?int'(random_state[0]):int'(random_state[2:0]);
                case(choice)
                    2:stimulus[bit_index]=1'bx;
                    3:stimulus[bit_index]=1'bz;
                    default:stimulus[bit_index]=random_state[0];
                endcase
            end
            check();
        end
        $display("BIAS_RANGE_FOUR_STATE_PASS samples=%0d comparisons=%0d unknown_inputs=%0d unknown_results=%0d",
                 checks,checks*16,unknown_inputs,unknown_results);
        $finish;
    end
endmodule
''')
    report = {'passed': False, 'inputs_constrained': False,
              'surrounding_logic_unchanged': True, 'strict_four_state_equivalence': True,
              'source_sha256': {label: {str(name): digest(root / name) for name in [SOURCE, HELPER]}
                                for label, root in roots.items()},
              'formal': [], 'four_state': []}
    for configuration in args.configurations:
        defines = [] if configuration == 'generic' else [
            '-D' + ('ASIC_SRAM' if configuration == 'asic' else 'XILINX_FPGA') + '=1']
        for width in WIDTHS:
            for share in (0, 1):
                stem = f'{configuration}_w{width}_s{share}'
                script, log = out / (stem + '.ys'), out / (stem + '.log')
                script.write_text('read_slang -DSYNTHESIS=1 ' + ' '.join(defines) +
                    f' --top proof -GW={width} -GSHARE={share} ' +
                    ' '.join(shlex.quote(str(path)) for path in models + [miter]) +
                    '\nprep -top proof -flatten\nopt_clean\ncheck -assert\n' +
                    'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
                text = execute([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], log)
                if 'SAT proof finished - no model found: SUCCESS!' not in text:
                    raise RuntimeError('范围比较证明未完成')
                report['formal'].append({'configuration': configuration, 'width': width,
                    'share_load_index': share, 'input_bits': 7 * width + 4,
                    'passed': True, 'log_sha256': digest(log)})
            stem = f'{configuration}_w{width}_four'
            binary, log = out / (stem + '.vvp'), out / (stem + '.log')
            execute(['iverilog', '-g2012', '-s', 'four_state', f'-Pfour_state.W={width}',
                     *defines, '-o', str(binary), *map(str, models), str(bench)],
                    out / (stem + '_build.log'))
            text = execute(['vvp', str(binary)], log)
            match = re.search(r'BIAS_RANGE_FOUR_STATE_PASS samples=(\d+) comparisons=(\d+) '
                              r'unknown_inputs=(\d+) unknown_results=(\d+)', text)
            if not match:
                raise RuntimeError('四态检查未完成')
            row = {'configuration': configuration, 'width': width, 'passed': True,
                   **dict(zip(['samples', 'comparisons', 'unknown_inputs', 'unknown_results'],
                              map(int, match.groups()))), 'log_sha256': digest(log)}
            report['four_state'].append(row)
            print(json.dumps(row), flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
