#!/usr/bin/env python3
"""证明实际累加器写入过程的次值、保持行为和全部写使能。"""
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
SOURCE = 'rtl/npu/conv/vector_engine.sv'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def section(source):
    start = source.index('  for (genvar entry=0;entry<TILE;entry++) begin : g_accumulator_write')
    end = source.index('  wire signed [63:0] rounding_input', start)
    return source[start:end]


def declarations(source):
    state = re.search(r'  typedef enum logic \[5:0\].*?} state_t;', source, re.S)[0]
    load = re.search(r'  typedef enum logic \[2:0\].*?} load_t;', source, re.S)[0]
    return state + '\n' + load + '\n'


def signals():
    return [
        ('logic', 'rst_n'), ('logic [5:0]', 'state'), ('logic [2:0]', 'load_kind'),
        ('vector_engine_pkg::vector_engine_cfg_t', 'c'),
        ('logic [ACTIVE_COUNT_W-1:0]', 'active'),
        ('logic [TILE_INDEX_W-1:0]', 'compute_index'),
        ('logic signed [31:0]', 'pe_result[PE_COUNT]'),
        ('logic signed [31:0]', 'bias_buf[TILE]'),
        ('logic', 'soft_exp_we'), ('logic [$clog2(TILE)-1:0]', 'soft_exp_index'),
        ('logic', 'rd_raw_valid'), ('logic [BUS_WIDTH-1:0]', 'rd_raw_data'),
        ('logic [31:0]', 'soft_lut_data'),
        ('logic', 'rd_valid[BUS_BYTES]'), ('logic signed [15:0]', 'rd_data[BUS_BYTES]'),
        ('logic [INPUT_INDEX_W-1:0]', 'rd_col_base'),
    ]


def unit(source, label, bus, tile, pe, formal=True):
    block = section(source)
    if formal:
        ff = '    always_ff @(posedge clk) if (rst_n) begin'
        assert block.count(ff) == 1
        init = '    always_comb begin\n      rhs_buf[entry] = prior_rhs[entry];\n      o_rhs_enable[entry] = 1\'b0;\n'
        init += '      acc_buf[entry] = prior_acc[entry];\n      o_enable[entry] = 1\'b0;\n'
        block = re.sub(r'acc_buf\[entry\]\s*<=\s*([^;]+);',
                           r"begin acc_buf[entry] = \1; o_enable[entry] = 1'b1; end", block)
        block = re.sub(r'rhs_buf\[entry\]\s*<=\s*([^;]+);',
                       r"begin rhs_buf[entry] = \1; o_rhs_enable[entry] = 1'b1; end", block)
        block = block.replace(ff, init + '      if (rst_n) begin')
        tail = '    end\n  end\n\n'
        assert block.endswith(tail)
        block = block[:-len(tail)] + '      end\n' + tail
    ports = []
    captures = []
    internal = []
    for typ, sig in signals():
        if formal:
            ports.append('input ' + typ + ' ' + sig)
        else:
            name = sig.split('[')[0]
            ports.append('input ' + typ + ' i_' + sig)
            internal.append(typ + ' ' + sig + ';')
            captures.append(name + ' <= i_' + name + ';')
    if formal:
        ports += ['input logic signed [31:0] prior_acc[TILE]',
                  'input logic signed [15:0] prior_rhs[TILE]',
                  'output logic [TILE-1:0] o_enable, o_rhs_enable']
    else:
        ports.insert(0, 'input logic clk')
    ports += ['output logic signed [31:0] acc_buf[TILE]',
              'output logic signed [15:0] rhs_buf[TILE]']
    header = f'''module {label} #(
  parameter int BUS_WIDTH={bus}, TILE={tile}, PE_COUNT={pe}, DMA_SIZE=4*TILE,
  BUS_BYTES=BUS_WIDTH/8, ACTIVE_COUNT_W=$clog2(TILE+1),
  TILE_INDEX_W=$clog2(TILE+PE_COUNT+1), INPUT_INDEX_W=$clog2(DMA_SIZE)
)(\n  ''' + ',\n  '.join(ports) + '\n);\n'
    body = '\n'.join(internal) + '\n' + declarations(source)
    body += '''  import vector_engine_pkg::*;
`ifdef XILINX_FPGA
  localparam bit p_offset_use_lut=1'b1;
`else
  localparam bit p_offset_use_lut=1'b0;
`endif
  logic depthwise, softmax_s8;
  logic signed [31:0] soft_exp_data;
  assign depthwise = c.op == DW_S8;
  assign softmax_s8 = c.op == SOFTMAX_S8;
  assign soft_exp_data = rd_raw_valid ? rd_raw_data[31:0] : soft_lut_data;
'''
    if not formal:
        body += 'always_ff @(posedge clk) begin\n' + '\n'.join(captures) + '\nend\n'
    return header + body + block + 'endmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='7ef39f0101ebf39184d11dbdc80a4042faee75c2')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference + ':' + SOURCE, cwd=ROOT, text=True)
    assert current.replace(section(current), section(reference), 1) == reference
    softmax = ROOT / 'rtl/npu/conv/vector_softmax.sv'
    assert 'assign exp_wdata = $signed(lut_rsp_data);' in softmax.read_text()
    assert '.lut_rsp_data(rd_raw_valid ? rd_raw_data[31:0] : soft_lut_data)' in current
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    primitive = re.search(r'^module LUT6\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    primitive_file = out / 'official_lut6.sv'
    primitive_file.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', primitive, flags=re.S) + '\n')
    packages = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    report = {'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
              'source_sha256': digest(current.encode()), 'reference_sha256': digest(reference.encode()),
              'outside_accumulator_block_unchanged': True, 'inputs_constrained': False,
              'scope': '全部累加器与 RHS 数据次值、无效周期保持、写使能、复位期间保持和同时写入优先级。',
              'softmax_data_identity_sha256': digest(softmax.read_bytes()),
              'primitive_library_sha256': digest(library.read_bytes()),
              'primitive_model_sha256': digest(primitive_file.read_bytes()), 'cases': []}
    for bus, tile, pe in ((32,16,8), (64,16,8), (128,16,8), (64,3,2), (32,1,1), (64,32,8)):
        folder = out / f'bus{bus}_tile{tile}_pe{pe}'
        folder.mkdir(exist_ok=True)
        models = {}
        for label, text in (('reference', reference), ('current', current)):
            path = folder / (label + '.sv')
            path.write_text(unit(text, label, bus, tile, pe))
            models[label] = path
        for fpga in (False, True):
            name = 'fpga' if fpga else 'generic'
            commands = []
            for label, path in models.items():
                sources = [*packages, path] + ([primitive_file] if fpga else [])
                flags = '-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC ' if fpga else '-D ASIC_SYNTHESIS '
                commands += ['read_slang --top ' + label + ' ' + flags + ' '.join(shlex.quote(str(p)) for p in sources),
                             'prep -top ' + label + ' -flatten', 'opt -full', 'design -stash ' + label]
            commands += ['design -copy-from reference reference', 'design -copy-from current current',
                         'miter -equiv -flatten reference current comparison', 'hierarchy -top comparison',
                         'opt -full', 'sat -verify -prove trigger 0 -show-inputs -show-outputs']
            script, log = folder / (name + '.ys'), folder / (name + '.log')
            script.write_text('\n'.join(commands) + '\n')
            command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)]
            with log.open('w') as stream:
                subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
            report['cases'].append({'bus_width': bus, 'tile': tile, 'pe_count': pe, 'implementation': name,
                                    'compared_bits': tile*50, 'passed': True,
                                    'command': command, 'log_sha256': digest(log.read_bytes()),
                                    'script_sha256': digest(script.read_bytes()),
                                    'model_sha256': {label: digest(path.read_bytes()) for label,path in models.items()}})
            print(f'{name} BUS{bus} TILE{tile} PE{pe}: passed', flush=True)
    assert current == (ROOT / SOURCE).read_text()
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'cases': len(report['cases']), 'source_sha256': report['source_sha256']}), flush=True)


if __name__ == '__main__':
    main()
