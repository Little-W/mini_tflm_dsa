#!/usr/bin/env python3
"""证明描述符行范围检查与33位无符号求和比较完全一致。"""
import argparse
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'rtl/npu/conv/conv_im2col_frontend.sv'


def request_cells(design):
    reached = set(design['ports']['tile_p0']['bits'] + design['ports']['tile_rows']['bits'])
    pending = {name: cell for name, cell in design['cells'].items()
               if re.fullmatch(r'LUT[1-6]|CARRY4|MUXF[78]|INV', cell['type'])}
    selected = {}
    while True:
        step = [name for name, cell in pending.items()
                if any(bit in reached for port, bits in cell['connections'].items()
                       if cell['port_directions'][port] == 'input' for bit in bits)]
        if not step:
            return selected
        for name in step:
            cell = pending.pop(name)
            selected[name] = cell
            reached.update(bit for port, bits in cell['connections'].items()
                           if cell['port_directions'][port] == 'output' for bit in bits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--measure', action='store_true', help='Also map the SIZE=16 range checker')
    parser.add_argument('--reference-ref', default='f5b7573')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text()
    start = source.index('  if (RW < 32) begin : g_tile_row_range')
    end = source.index('  // Configuration-time products', start)
    body = source[start:end]
    assignment = re.search(r'position_high_minus_one_q <= ([^;]*cfg_positions[^;]*);', source)
    if assignment is None:
        raise ValueError('configuration boundary assignment missing')
    capture = assignment.group(1).replace('cfg_positions', 'position_count')
    cases = []
    for width in (1, 2, 3, 4, 5, 8, 16, 31, 32, 33):
        directory = out / f'rw{width}'
        directory.mkdir(exist_ok=True)
        miter = directory / 'row_range_miter.sv'
        miter.write_text(f'''module row_range_miter (
  input logic [31:0] tile_p0, position_count,
  input logic [{width-1}:0] tile_rows,
  output logic equivalent
);
localparam int RW={width};
localparam int p_row_low_w = RW < 32 ? RW : 31;
localparam int p_row_high_w = 32 - p_row_low_w;
logic [p_row_high_w-1:0] position_high_minus_one_q;
logic tile_rows_in_range;
assign position_high_minus_one_q = {capture};
{body}
assign equivalent = tile_rows_in_range == ({{1'b0,tile_p0}} + 33'(tile_rows) <= {{1'b0,position_count}});
endmodule
''')
        script = directory / 'run.ys'
        script.write_text('read_slang --top row_range_miter ' + shlex.quote(str(miter)) + '\n' +
                          'prep -top row_range_miter -flatten\n' +
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        log_path = directory / 'proof.log'
        with log_path.open('w') as log:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log_path.read_text():
            raise AssertionError(f'SAT success marker missing: {directory}')
        cases.append({'RW': width, 'passed': True})
    result = {'passed': True, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'inputs_constrained': False, 'scope': 'all tile_p0, tile_rows and position_count encodings',
              'configurations': cases}
    if args.measure:
        original = read_rtl_source(args.reference_ref +
            ':rtl/npu/conv/conv_im2col_frontend.sv', cwd=ROOT, text=True)
        condition = re.search(r"\(\{1'b0,tile_p0\}\+33'\(tile_rows\)\s*>\s*\{1'b0,position_count\}\)", original)
        if condition is None:
            raise ValueError('reference range comparison missing')
        reference_body = 'assign tile_rows_in_range = !' + condition.group(0) + ';\n'
        spec = importlib.util.spec_from_file_location('fpga_synth', ROOT / 'scripts/fpga/open_fpga_synth.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        measurements = {}
        for name, code in [('reference', reference_body), ('current', body)]:
            directory = out / ('mapped_' + name)
            directory.mkdir(exist_ok=True)
            rtl = directory / 'row_range.sv'
            prepare = ''
            reset = ''
            if name == 'current':
                prepare = 'position_high_minus_one_q <= ' + capture.replace('position_count', 'cfg_positions') + ';'
                reset = "position_high_minus_one_q <= '1;"
            rtl.write_text(f'''module row_range (
  input logic clk, rst_n, cfg_valid,
  input logic [31:0] cfg_positions, tile_p0,
  input logic [4:0] tile_rows,
  output logic tile_rows_in_range
);
localparam int RW=5, p_row_low_w=5, p_row_high_w=27;
logic [31:0] position_count;
logic [p_row_high_w-1:0] position_high_minus_one_q;
always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin position_count <= '0; {reset} end
  else if (cfg_valid) begin position_count <= cfg_positions; {prepare} end
end
{code}
endmodule
''')
            mapped = directory / 'mapped.json'
            script = directory / 'run.ys'
            script.write_text('read_slang --top row_range ' + shlex.quote(str(rtl)) + '\n' +
                'synth_xilinx -top row_range -family xc7 -noiopad -noclkbuf -flatten\n' +
                'check -assert\nstat -tech xilinx\nwrite_json ' + shlex.quote(str(mapped)) + '\n')
            with (directory / 'synthesis.log').open('w') as log:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
            design = json.loads(mapped.read_text())['modules']['row_range']
            cells = design['cells']
            counts = collections.Counter(cell['type'] for cell in cells.values())
            path = module.logic_depth(cells)
            request_path = module.logic_depth(request_cells(design))
            measurements[name] = {'lut_cells': sum(n for cell, n in counts.items() if re.fullmatch('LUT[1-6]', cell)),
                'flip_flops': sum(n for cell, n in counts.items() if cell.startswith(('FDCE', 'FDPE', 'FDRE', 'FDSE'))),
                'carry4': counts['CARRY4'], 'longest_combinational_path_cells': len(path),
                'longest_combinational_path': path,
                'request_combinational_path_cells': len(request_path), 'request_combinational_path': request_path}
        result.update(range_checker_resources=measurements, reference_ref=args.reference_ref,
                      reference_sha256=hashlib.sha256(original.encode()).hexdigest())
        print(json.dumps(measurements))
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('FRONTEND_ROW_RANGE_EQUIVALENCE_PASS', len(cases), out / 'summary.json')


if __name__ == '__main__':
    main()
