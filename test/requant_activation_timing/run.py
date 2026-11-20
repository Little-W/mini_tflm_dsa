#!/usr/bin/env python3
"""验证量化激活比较的完整数值关系、寄存周期与原生逻辑深度。"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
sys.path.insert(0, str(ROOT / 'test'))
from netlist_metrics import connected_paths, resources
from open_fpga_synth import run_stage
from rtl_reference import read_rtl_source

SOURCE = Path('rtl/npu/writeback/vec_requant.sv')
LANE_SOURCE = Path('rtl/npu/writeback/requant_compute_lane.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_unit(compare_source, lane_source):
    compare = re.search(r'module requant_activation_compare\b.*?endmodule',
                        compare_source, re.S).group()
    begin = lane_source.index('            if (!lane_enable_q[p_stages-2]) begin')
    end = lane_source.index('\n        end\n    end\nendmodule', begin)
    selection = lane_source[begin:end]
    replacements = {
        'lane_enable_q[p_stages-2]': 'i_lane_enable', 'sum_o_value': 'i_value',
        'i_activation_min': 'i_minimum', 'i_activation_max': 'i_maximum',
        'compare_o_below': 'below', 'compare_o_above': 'above', '<=': '=',
    }
    for old, new in replacements.items():
        selection = selection.replace(old, new)
    return compare + '''
module activation_output (
    input logic signed [35:0] i_value,
    input logic signed [31:0] i_minimum, i_maximum,
    input logic i_lane_enable,
    output logic signed [7:0] o_s8,
    output logic signed [15:0] o_s16
);
    logic below, above;
    requant_activation_compare u_compare (
        .i_value(i_value), .i_minimum(i_minimum), .i_maximum(i_maximum),
        .o_below_minimum(below), .o_above_maximum(above)
    );
    always_comb begin
''' + selection + '\n    end\nendmodule\n'


def paths_between_ports(module):
    measured = copy.deepcopy(module)
    next_bit = max(bit for net in measured['netnames'].values()
                   for bit in net['bits'] if isinstance(bit, int)) + 1
    for name, port in measured['ports'].items():
        for index, bit in enumerate(port['bits']):
            if not isinstance(bit, int):
                continue
            connection = {'C': ['0'], 'CE': ['1'], 'R': ['0']}
            if port['direction'] == 'input':
                connection.update(Q=[bit], D=['0'])
            else:
                connection.update(D=[bit], Q=[next_bit])
                next_bit += 1
            measured['cells'][f'boundary_{name}_{index}'] = {
                'type': 'FDRE', 'parameters': {}, 'connections': connection,
                'port_directions': {'C': 'input', 'CE': 'input', 'R': 'input',
                                    'D': 'input', 'Q': 'output'},
            }
    result = connected_paths(measured, limit=3, group_limit=3)
    if not result['graph_complete']:
        raise RuntimeError('组合输出路径未完整识别')
    return result


def mapping_script(source, mapped, library):
    return f'''read_slang --top activation_output {shlex.quote(str(source))}
synth_xilinx -top activation_output -family xc7 -nodsp -nosrl -noiopad -noclkbuf -run begin:map_luts
read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v
read_verilog -lib -overwrite +/xilinx/cells_xtra.v
opt_expr -mux_undef -noclkinv
read_verilog -icells -lib -specify +/xilinx/abc9_model.v
scratchpad -set abc9.xaiger 1
scratchpad -set abc9.verify 1
abc9 -W 500 -lut {shlex.quote(str(library))} -D 6667
clean
techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6
xilinx_dffopt
opt_lut_ins -tech xilinx
synth_xilinx -top activation_output -family xc7 -noiopad -noclkbuf -run finalize:
check -assert
write_json {shlex.quote(str(mapped))}
stat
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='9a6437f4')
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_hashes = {str(path): digest(ROOT / path) for path in (SOURCE, LANE_SOURCE)}
    formal = out / 'formal'
    with (out / 'formal.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'test/requant_activation_compare/run_formal.py'),
                        '--out', str(formal)], cwd=ROOT, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    reference = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    lane_source = (ROOT / LANE_SOURCE).read_text()
    library = out / 'unit_lut_cost.lut'
    library.write_text(''.join(f'{width} 1 1\n' for width in range(1, 7)))
    mapping = {}
    for label, text in (('reference', reference), ('current', current)):
        folder = out / label
        folder.mkdir(exist_ok=True)
        source = folder / 'activation_output.sv'
        source.write_text(output_unit(text, lane_source))
        mapped = folder / 'mapped.json'
        script = folder / 'synthesis.ys'
        script.write_text(mapping_script(source, mapped, library))
        stage = run_stage(script, folder / 'synthesis.log', dict(os.environ))
        module = json.loads(mapped.read_text())['modules']['activation_output']
        mapping[label] = {'resources': resources(module['cells']),
                          'paths': paths_between_ports(module),
                          'extracted_source_sha256': digest(source),
                          'mapped_json_sha256': digest(mapped), 'stage': stage}
        with mapped.open('rb') as stream, gzip.open(str(mapped) + '.gz', 'wb') as target:
            shutil.copyfileobj(stream, target)
        mapped.unlink()
    numeric = out / 'numeric'
    with (out / 'numeric.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'test/requant_compute_lane/run.py'),
                        '--out', str(numeric), '--verilator', args.verilator, '--jobs', '1'],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    for label in ('generic', 'fpga'):
        folder = numeric / label
        shutil.copy2(folder / 'obj/Vrequant_compute_lane', folder / 'Vrequant_compute_lane')
        shutil.rmtree(folder / 'obj')
    if source_hashes != {str(path): digest(ROOT / path) for path in (SOURCE, LANE_SOURCE)}:
        raise RuntimeError('验证期间 RTL 内容发生变化')
    report = {
        'passed': True, 'reference_revision': args.reference, 'source_sha256': source_hashes,
        'formal': json.loads((formal / 'summary.json').read_text()),
        'numeric': json.loads((numeric / 'summary.json').read_text()),
        'mapping': mapping, 'dsp_remapping': False, 'physical_lut_packing': False,
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({
        'passed': True,
        'mapping': {label: {'logic_lut': row['resources']['logic_lut_cells'],
                            'carry4': row['resources']['carry4'],
                            'levels': row['paths']['longest_register_path_cells']}
                    for label, row in mapping.items()},
        'numeric': report['numeric']['cases'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
