#!/usr/bin/env python3
"""穷举量化运行许可与批次完成条件的四态输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/writeback/vec_requant.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualification_unit(text, name):
    text = text.split('module vec_requant_full #(', 1)[1]
    configuration = re.search(r'  wire cfg_per_channel_eff =.*?;', text, re.S)[0]
    if '  wire cfg_control_per_channel;' in text:
        first = text.index('  wire cfg_control_per_channel;')
        configuration += '\n' + text[first:text.index('`endif', first) + len('`endif')]
    else:
        configuration += '\n  wire cfg_control_per_channel = cfg_per_channel_eff;'
    first = text.index('  if (p_compute_lanes < VLEN) begin : g_serial_arithmetic')
    current = text.index('    assign issue_valid =', first)
    if 'logic row_batch_ready;' in text[first:current]:
        current = text.index('    (* keep = 1 *) logic row_batch_ready;', first)
    last = text.index('    assign row_consume_tile_done =', current)
    selection = text[current:last]
    return f'''module {name} #(parameter integer ENABLE_PER_CHANNEL=1)(
    input logic cfg_per_channel, serial_per_channel_q, quant_params_valid,
    input logic init_cfg, row_o_valid, parameters_ready_q,
    input logic [2:0] batch_q,
    output logic [3:0] result
);
    localparam integer VLEN=16, p_compute_lanes=2, p_batches=8, p_batch_width=3;
    wire issue_valid, row_consume_valid, last_batch;
{configuration}
{selection}
    assign result = {{cfg_per_channel_eff,
        (init_cfg ? cfg_per_channel_eff : cfg_control_per_channel),
        issue_valid, row_consume_valid}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {'reference': args.reference_root.resolve() / RTL,
             'current': args.source_root.resolve() / RTL}
    hashes = {label: digest(path) for label, path in paths.items()}
    units = []
    for label, path in paths.items():
        unit = out / (label + '.sv')
        unit.write_text(qualification_unit(path.read_text(), label))
        units.append(unit)
    bench = out / 'tb.sv'
    bench.write_text('''module tb;
    logic [8:0] controls;
    wire [3:0] expected [2], observed [2];
    integer checks=0;
    for (genvar enabled=0;enabled<2;enabled++) begin : g_profile
        reference #(.ENABLE_PER_CHANNEL(enabled)) u_reference(
            .cfg_per_channel(controls[0]), .serial_per_channel_q(controls[1]),
            .quant_params_valid(controls[2]), .init_cfg(controls[3]),
            .row_o_valid(controls[4]), .parameters_ready_q(controls[5]),
            .batch_q(controls[8:6]), .result(expected[enabled]));
        current #(.ENABLE_PER_CHANNEL(enabled)) u_current(
            .cfg_per_channel(controls[0]), .serial_per_channel_q(controls[1]),
            .quant_params_valid(controls[2]), .init_cfg(controls[3]),
            .row_o_valid(controls[4]), .parameters_ready_q(controls[5]),
            .batch_q(controls[8:6]), .result(observed[enabled]));
    end
    function automatic logic symbol(input integer value);
        case(value)
            0: symbol=1'b0;
            1: symbol=1'b1;
            2: symbol=1'bx;
            3: symbol=1'bz;
        endcase
    endfunction
    initial begin
        for (integer sample=0;sample<262144;sample++) begin
            for (integer bit_index=0;bit_index<9;bit_index++)
                controls[bit_index]=symbol((sample>>(2*bit_index))&3);
            #1;
            for (integer enabled=0;enabled<2;enabled++) begin
                if (observed[enabled] !== expected[enabled])
                    $fatal(1,"qualification mismatch sample=%0d enabled=%0d",sample,enabled);
                checks++;
            end
        end
        $display("PASS controls=%0d checks=%0d",262144,checks);
        $finish;
    end
endmodule
''')
    log = out / 'run.log'
    binary = out / 'simulation'
    with log.open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                        *map(str, units), str(bench)], check=True,
                       stdout=stream, stderr=subprocess.STDOUT, timeout=60)
        subprocess.run(['vvp', str(binary)], check=True,
                       stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    if 'PASS controls=262144 checks=524288' not in log.read_text():
        raise RuntimeError('四态穷举未完成')
    if hashes != {label: digest(path) for label, path in paths.items()}:
        raise RuntimeError('验证期间源文件发生变化')
    report = {'passed': True, 'source_sha256': hashes, 'strict_four_state': True,
              'input_bits': 9, 'exhaustive_assignments': 262144,
              'profiles': [0, 1], 'comparisons': 524288, 'compared_flags': 4,
              'bench_sha256': digest(bench), 'log_sha256': digest(log)}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
