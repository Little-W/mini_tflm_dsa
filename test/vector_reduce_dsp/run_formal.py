#!/usr/bin/env python3
"""比较实际向量归约代码，对全部 INT32 输入验证 DSP 与通用实现。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def normalized(source):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='90ac3639')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(
        ['git', 'show', revision + ':rtl/npu/conv/vector_engine.sv'], cwd=ROOT, text=True)
    current = (ROOT / 'rtl/npu/conv/vector_engine.sv').read_text()
    ref_first = reference.index('  logic [31:0] reduce_sum;')
    ref_last = reference.index('  localparam int POOL_SUM_WIDTH=', ref_first)
    cur_first = current.index('  logic signed [31:0] reduce_alu_i_lhs')
    cur_last = current.index('  localparam int POOL_SUM_WIDTH=', cur_first)
    assert normalized(reference[:ref_first] + reference[ref_last:]) == normalized(
        current[:cur_first] + current[cur_last:])
    old_pe = subprocess.check_output(
        ['git', 'show', revision + ':rtl/npu/conv/vector_pe.sv'], cwd=ROOT, text=True)
    current_pe = (ROOT / 'rtl/npu/conv/vector_pe.sv').read_text()
    retained_pe = current_pe[:current_pe.index('module vector_reduce_alu')] + '\n`default_nettype wire\n'
    assert normalized(old_pe) == normalized(retained_pe)
    header = '''(input logic clk, input vector_engine_pkg::vector_engine_cfg_t c,
input logic signed [31:0] reduce_acc,serial_acc_read_data,output logic signed [31:0] reduce_next);
import vector_engine_pkg::*;
'''
    sections = out / 'reduce_sections.sv'
    sections.write_text('module reduce_reference ' + header + reference[ref_first:ref_last] +
                        '\nendmodule\nmodule reduce_current ' + header + current[cur_first:cur_last] +
                        '\nendmodule\n')
    proof = out / 'reduce_proof.sv'
    proof.write_text('''module reduce_proof(input logic clk,
input logic signed [31:0] i_acc,i_data,input logic [3:0] i_op,output logic equivalent);
vector_engine_pkg::vector_engine_cfg_t c;
logic signed [31:0] reference_result,current_result;
always_comb begin c='0; c.op=i_op; end
reduce_reference u_reference(.clk,.c,.reduce_acc(i_acc),.serial_acc_read_data(i_data),.reduce_next(reference_result));
reduce_current u_current(.clk,.c,.reduce_acc(i_acc),.serial_acc_read_data(i_data),.reduce_next(current_result));
assign equivalent = reference_result == current_result;
endmodule
''')
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'dsp_model.sv'
    primitive = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S).group()
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', primitive, flags=re.S) + '\n')
    sources = [ROOT / 'rtl/npu/conv' / name for name in
               ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv', 'vector_pe.sv', 'vector_engine.sv')]
    sources.append(Path(__file__).resolve())
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    report = {'reference_revision': revision, 'source_sha256': hashes,
              'reference_engine_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'outside_reduction_unchanged': True, 'existing_pe_unchanged': True,
              'input_scope': 'All pairs of signed 32-bit operands and all 16 operation codes.',
              'results': {}}
    for mode in ('fpga', 'generic'):
        script = out / (mode + '.ys')
        define = '' if mode == 'fpga' else ' -D ASIC_SYNTHESIS=1'
        script.write_text(f'''read_slang -D SYNTHESIS=1 -D VERIFIC=1 -D YOSYS=1{define} --top reduce_proof rtl/npu/conv/conv_im2col_pkg.sv rtl/npu/conv/vector_engine_pkg.sv rtl/npu/conv/vector_pe.sv {sections} {proof} {model}
prep -top reduce_proof -flatten
opt -full
sat -verify -prove equivalent 1 -show-inputs -show-outputs
''')
        log = out / (mode + '.log')
        with log.open('w') as output:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=120)
        if result.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError(f'Reduction equivalence did not pass: {log}')
        report['results'][mode] = {'passed': True, 'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
                                  'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    if hashes != {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashes}:
        raise RuntimeError('Sources changed during validation')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'implementations': list(report['results'])}))


if __name__ == '__main__':
    main()
