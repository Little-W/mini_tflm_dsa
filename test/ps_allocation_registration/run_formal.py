#!/usr/bin/env python3
"""提取真实配置接收逻辑，证明共享银行状态和所有派生输出逐周期相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')
LIMITS = Path('rtl/npu/control/ps_capacity_limits.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def allocation_module(source):
    start = '    logic [31:0] shared_ia_banks_q;'
    end = '    wire shared_ram_capacity_fault;'
    if source.count(start) != 1 or source.count(end) != 1:
        raise RuntimeError('Expected one allocation declaration region')
    declarations = start + source.split(start, 1)[1].split(end, 1)[0]
    capture_start_match = re.search(r'        wire cfg_start_event(?: = [^;]+)?;\n', source)
    capture_end = '        assign cfg_stage2_fire ='
    if capture_start_match is None or source.count(capture_end) != 1:
        raise RuntimeError('Expected one allocation capture region')
    capture_start = capture_start_match[0]
    capture = source.split(capture_start, 1)[1].split(capture_end, 1)[0]
    observer = ''
    if 'logic [SHARED_PHYSICAL_BANKS_WIDTH-1:0] active_ps_bank_count_q;' not in declarations:
        observer = '''
    wire [SHARED_PHYSICAL_BANKS_WIDTH-1:0] active_ps_bank_count_q =
        SHARED_PHYSICAL_BANKS_WIDTH'(active_ps_bank_count);
    wire shared_allocation_invalid_q = shared_allocation_invalid;
'''
    header = '''module allocation_measure #(
    parameter int p_total_banks=7, p_bank_bytes=8192, p_max_rows=512,
    parameter bit p_shared=1'b1,
    parameter int p_rows_width=$clog2(p_max_rows+1), p_frames_width=5
) (
    input logic clk, core_rst_n, cfg_start_event,
    input logic [31:0] cfg_shared_ia_banks,
    input logic cfg_stream_compact,
    input logic [p_rows_width-1:0] i_frame_rows,
    input logic [p_frames_width-1:0] i_frames,
    input logic [31:0] i_slice_tiles,
    input logic i_use_frames, i_capacity_capture,
    output logic [31:0] o_ia_banks, o_ps_banks, o_cache_blocks, o_pool_bytes, o_bank_depth,
    output logic o_allocation_invalid,
    output logic o_frames_fit, o_admission_fit
);
    localparam bit SHARED_RAM_ENABLED=p_shared;
    localparam int SHARED_BANK_BYTES=p_bank_bytes;
    localparam int SHARED_TOTAL_BYTES=p_bank_bytes*p_total_banks;
    localparam int SHARED_PHYSICAL_BANKS=p_total_banks;
    localparam int SHARED_PHYSICAL_BANKS_WIDTH=$clog2(p_total_banks+1)>0 ? $clog2(p_total_banks+1) : 1;
    localparam int IA_CACHE_BLOCKS=32;
'''
    footer = '''
    assign o_ia_banks=shared_ia_banks_q;
    assign o_ps_banks=active_ps_bank_count;
    assign o_cache_blocks=active_ia_cache_blocks;
    assign o_pool_bytes=active_ps_pool_bytes;
    assign o_bank_depth=active_ps_bank_depth;
    assign o_allocation_invalid=shared_allocation_invalid;
    logic frames_fit, admission_fit;
    if (p_shared) begin : g_capacity
        ps_capacity_limits #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),
            .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),
            .p_bank_bytes(p_bank_bytes), .p_tile_shift(4)) u_capacity (
            .i_frame_rows(i_frame_rows), .i_frames(i_frames), .i_bank_count(active_ps_bank_count),
            .i_frame_slice_tiles(i_slice_tiles), .i_use_frame_commands(i_use_frames),
            .o_frames_fit(frames_fit), .o_admission_fit(admission_fit));
    end else begin : g_fixed
        assign frames_fit=1'b1;
        assign admission_fit=1'b1;
    end
    always_ff @(posedge clk) begin
        if (i_capacity_capture) begin
            o_frames_fit<=frames_fit;
            o_admission_fit<=admission_fit;
        end
    end
endmodule
'''
    return header + declarations + observer + capture + footer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='087542cb')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(path): digest(ROOT / path) for path in (TOP, LIMITS)}
    snapshots = {}
    for label in ('reference', 'current'):
        source = (read_rtl_source(f'{args.reference_rev}:{TOP}', cwd=ROOT, text=True)
                  if label == 'reference' else (ROOT / TOP).read_text())
        snapshots[label] = out / (label + '.sv')
        snapshots[label].write_text(allocation_module(source))
    report = {'passed': False, 'reference_rev': args.reference_rev,
              'source_sha256': hashes, 'inputs_constrained': False,
              'configuration_input_bits': 32,
              'generated_sha256': {label: digest(path) for label, path in snapshots.items()},
              'profiles': []}
    profiles = [(banks, bank_bytes, 1) for banks in (6, 7, 8, 9)
                for bank_bytes in (2048, 4096, 8192)] + [(1, 8192, 0), (7, 8192, 0)]
    for banks, bank_bytes, shared in profiles:
        max_rows = (4 if banks >= 8 else 2) * bank_bytes // 512 * 16
        folder = out / f'banks{banks}_bytes{bank_bytes}_shared{shared}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, source in snapshots.items():
            commands += [
                'read_slang --top allocation_measure -DGEMMORA_PS_POOL_BYTES=49152 '
                f'-Gp_total_banks={banks} -Gp_bank_bytes={bank_bytes} '
                f'-Gp_max_rows={max_rows} -Gp_shared={shared} '
                + shlex.quote(str(source)) + ' ' + shlex.quote(str(ROOT / LIMITS)),
                'prep -top allocation_measure -flatten', 'memory_map', 'async2sync', 'opt_clean',
                f'rename allocation_measure {label}', f'design -stash {label}',
            ]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = folder / 'run.ys'
        log = folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        case = {'total_banks': banks, 'bank_bytes': bank_bytes, 'shared': bool(shared),
                'max_rows': max_rows,
                'passed': result.returncode == 0 and 'Equivalence successfully proven' in text,
                'equivalent_bits': int(match[1]) if match else None,
                'script_sha256': digest(script), 'log_sha256': digest(log)}
        report['profiles'].append(case)
        print(json.dumps(case), flush=True)
        if not case['passed']:
            raise RuntimeError(f'Formal comparison did not complete: {log}')
    if hashes != {str(path): digest(ROOT / path) for path in (TOP, LIMITS)}:
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
