#!/usr/bin/env python3
"""验证已登记描述符比较结果的输入稳定性及预取等待状态。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    'rtl/npu/loaders/kernel_loader.sv',
    'rtl/npu/loaders/kernel_loader_ctrl.sv',
    'rtl/npu/loaders/kernel_loader_buffer.sv',
    'rtl/common/regfile.v',
    'rtl/common/add_equal.sv',
    'rtl/common/add3_equal.sv', 'rtl/common/parallel_prefix_add.sv',
)
OBSERVATION = '''
    logic initial_cycle = 1'b1;
    logic rst_n;
    always_ff @(posedge clk) initial_cycle <= 1'b0;
    assign rst_n = requested_rst_n && !initial_cycle;
    logic [677:0] comparison_inputs, comparison_inputs_q;
    assign comparison_inputs = {
        dut.ctrl_descriptor.im2col, dut.ctrl_descriptor.use16, dut.ctrl_descriptor.tile_packed,
        dut.ctrl_descriptor.row_stride, dut.ctrl_descriptor.group, dut.ctrl_descriptor.rows,
        dut.ctrl_descriptor.cols, dut.ctrl_descriptor.zp,
        dut.comparison_descriptor.im2col, dut.comparison_descriptor.use16, dut.comparison_descriptor.tile_packed,
        dut.comparison_descriptor.row_stride, dut.comparison_descriptor.group, dut.comparison_descriptor.rows,
        dut.comparison_descriptor.cols, dut.comparison_descriptor.zp,
        dut.column_equal_i_a, dut.column_equal_i_b, dut.column_equal_i_c, dut.column_equal_i_target,
        dut.row_equal_i_a, dut.row_equal_i_b, dut.row_equal_i_target,
        dut.address_equal_i_a, dut.address_equal_i_b, dut.address_equal_i_c, dut.address_equal_i_target
    };
    always_ff @(posedge clk) comparison_inputs_q <= comparison_inputs;
    assign comparison_stable = !rst_n || !dut.comparison_ready || comparison_inputs == comparison_inputs_q;
    assign pending_visible = !rst_n || !dut.prefetch_candidate_valid || dut.comparison_ready || !prefetch_idle;
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_worker(path, log):
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(path)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'Formal tool failed: {log}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {path: digest(ROOT / path) for path in SOURCE_PATHS}
    tb = (ROOT / 'test/kernel_prefetch/tb.sv').read_text()
    tb = tb.replace('kernel_prefetch_tb', 'kernel_compare_proof')
    tb = tb.replace('input logic clk,rst_n,init_cfg', 'input logic clk,requested_rst_n,init_cfg')
    tb = tb.replace('output wire [15:0] dbg_ram_write_en,dbg_ram_read_en',
                    'output wire [15:0] dbg_ram_write_en,dbg_ram_read_en,\n    output logic comparison_stable,pending_visible')
    tb = tb.replace('    kernel_loader #', OBSERVATION + '\n    kernel_loader #')
    wrapper = out / 'kernel_compare_proof.sv'
    wrapper.write_text(tb)
    reports = []
    for count_width, bus_width in ((8, 32), (29, 32), (29, 64)):
        folder = out / f'count{count_width}_bus{bus_width}'
        folder.mkdir(exist_ok=True)
        design_path = folder / 'complete.json'
        script = folder / 'elaborate.ys'
        script.write_text('read_slang -D ASIC_SYNTHESIS=1 --top kernel_compare_proof '
                          f'-GCOUNT_WIDTH={count_width} -GBUS_WIDTH={bus_width} ' +
                          ' '.join(shlex.quote(str(path)) for path in [wrapper] + [ROOT / p for p in SOURCE_PATHS]) +
                          '\nprep -top kernel_compare_proof -flatten\nwrite_json ' + shlex.quote(str(design_path)) + '\n')
        run_worker(script, folder / 'elaborate.log')
        design = json.loads(design_path.read_text())
        module = design['modules']['kernel_compare_proof']
        module['ports'] = {name: value for name, value in module['ports'].items()
                           if value['direction'] == 'input' or name in ('comparison_stable', 'pending_visible')}
        cuts = ['dut.comparison_equal', 'dut.u_ctrl.load_limit_o_ge', 'dut.u_ctrl.sent_count_covers_loads',
                'dut.u_ctrl.last_col_in_group', 'dut.u_ctrl.last_tile_row',
                'dut.u_ctrl.last_l2_group', 'dut.u_ctrl.last_repeat']
        next_bit = max(bit for net in module['netnames'].values() for bit in net['bits'] if isinstance(bit, int)) + 1
        for name in cuts:
            bits = module['netnames'][name]['bits']
            assert len(bits) == 1 and isinstance(bits[0], int)
            bit = bits[0]
            drivers = []
            for cell_name, cell in module['cells'].items():
                for port, connection in cell['connections'].items():
                    if cell['port_directions'][port] == 'output' and bit in connection:
                        drivers.append((cell_name, port))
                        cell['connections'][port] = [next_bit if item == bit else item for item in connection]
            assert len(drivers) == 1, (name, drivers)
            next_bit += 1
            input_name = 'unconstrained_' + name.replace('.', '_')
            module['ports'][input_name] = {'direction': 'input', 'bits': bits}
            module['netnames'][input_name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
        model_path = folder / 'abstracted.json'
        model_path.write_text(json.dumps(design))
        proof = folder / 'prove.ys'
        proof.write_text('read_json ' + shlex.quote(str(model_path)) +
                         '\nhierarchy -top kernel_compare_proof\nopt_clean\nmemory_map\nasync2sync\nopt -full\n'
                         'sat -verify -tempinduct -seq 2 -maxsteps 6 -timeout 45 -set-init-zero '
                         '-prove comparison_stable 1 -prove pending_visible 1 -show-inputs -show-outputs\n')
        proof_log = folder / 'prove.log'
        run_worker(proof, proof_log)
        if 'Induction step proven: SUCCESS!' not in proof_log.read_text():
            raise RuntimeError(f'Comparison preparation proof incomplete: {proof_log}')
        reports.append({'COUNT_WIDTH': count_width, 'BUS_WIDTH': bus_width, 'passed': True,
                        'control_overapproximations': cuts, 'source_input_constraints': False,
                        'log_sha256': digest(proof_log), 'model_sha256': digest(model_path)})
        print(json.dumps(reports[-1]), flush=True)
    if hashes != {path: digest(ROOT / path) for path in SOURCE_PATHS}:
        raise RuntimeError('RTL source changed during proof')
    report = {'passed': True, 'source_sha256': hashes, 'profiles': reports,
              'comparison_input_bits': 678,
              'properties': ['comparison_ready preserves every comparison input since sampling',
                             'a candidate waiting for comparison keeps prefetch_idle low']}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
