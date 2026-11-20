#!/usr/bin/env python3
"""比较实际量化乘积阶段、共享乘法器和独立 INT64 数值参考。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def make_reference(revision):
    old = read_rtl_source(revision + ':rtl/npu/writeback/vec_requant.sv', cwd=ROOT, text=True)
    full = old.split('module vec_requant_full #(', 1)[1].split('\nendmodule', 1)[0]
    updates = [re.search(r'\b' + name + r'\s*<=.*?;', full, re.S)[0]
               for name in ('product_low_s1', 'product_high_s1', 'product_low_s2')]
    updates = [item.replace('acc_s0', 'i_a').replace('mult_s0', 'i_b') for item in updates]
    declarations = re.search(r'    logic product_sum_i_en;.*?logic signed \[47:0\] product_sum_o_sum;', full, re.S)[0]
    begin = full.index('    assign product_sum_i_en =')
    end = full.index('    );', begin) + len('    );')
    bindings = full[begin:end].replace('!init_cfg', 'i_en')
    helper = re.search(r'^module requant_registered_sum\b.*?^endmodule', old, re.M | re.S)[0]
    reference = '''module quant_product_reference(
        input logic clk,i_en,
        input logic signed [31:0] i_a,i_b,
        output logic signed [63:0] o_product
    );
        logic signed [47:0] product_low_s1,product_high_s1,product_high_s2;
        logic [15:0] product_low_s2;
    ''' + declarations + '\n' + bindings + '\n'
    reference += 'always_ff @(posedge clk) if(i_en) begin\n' + '\n'.join(updates) + '\nend\n'
    reference += 'assign o_product={product_high_s2,product_low_s2};\nendmodule\n' + helper + '\n'
    return reference, old


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='038a095')
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, old = make_reference(args.reference_rev)
    reference_path = out / 'reference.sv'
    reference_path.write_text(reference)
    source = ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv'
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model_path = out / 'dsp48e1.sv'
    model_path.write_text(model + '\n')
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal', '-DSYNTHESIS',
               '--top-module', 'tb_requant_product', '-j', '2', '--Mdir', str(out / 'obj'),
               str(source), str(reference_path), str(model_path), str(HERE / 'tb_requant_product.sv')]
    with (out / 'build.log').open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(out / 'obj/Vtb_requant_product')], capture_output=True, text=True, check=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    line = next(line for line in result.stdout.splitlines() if line.startswith('REQUANT_PRODUCT_PASS'))
    summary = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
    summary.update(passed=True, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                   reference_rev=args.reference_rev, reference_source_sha256=hashlib.sha256(old.encode()).hexdigest(),
                   primitive_library_sha256=hashlib.sha256(library.read_bytes()).hexdigest())
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
