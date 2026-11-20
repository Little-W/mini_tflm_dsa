#!/usr/bin/env python3
"""验证共享地址加法的完整结果、实际读取译码和所有输入条件。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_engine.sv'


def normalized(source):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S))


def execute(script, log):
    with log.open('w') as output:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, timeout=180)
    if result.returncode:
        raise RuntimeError(f'Formal verification did not complete: {log}')
    return hashlib.sha256(log.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='e6fd2b1f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    reference = read_rtl_source(revision + ':' + SOURCE, cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    helper = re.search(r'^module vector_read_address_add\b.*?^endmodule', current, re.M | re.S).group()
    reference_remainder = re.sub(
        r'  assign \{unused_read_address_carry, rd_base_addr\} =.*?;', '', reference, count=1, flags=re.S)
    current_remainder = re.sub(r'  vector_read_address_add u_read_address \(.*?\);',
                               '', current.replace(helper, ''), count=1, flags=re.S)
    assert normalized(reference_remainder) == normalized(current_remainder)
    helper_file = out / 'address_helper.sv'
    helper_file.write_text(helper + '\n')

    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    library_text = library.read_text()
    models = []
    for name in ('LUT6_2', 'DSP48E1'):
        block = re.search(r'^module ' + name + r'\b.*?^endmodule', library_text, re.M | re.S).group()
        models.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', block, flags=re.S))
    model_file = out / 'primitive_models.sv'
    model_file.write_text('\n\n'.join(models) + '\n')
    proof = out / 'address_proof.sv'
    proof.write_text('''module address_proof(input logic clk,
input logic [31:0] i_base,i_offset,input logic [15:0] i_channel,
output logic equivalent);
logic [31:0] address;
logic [1:0] carry;
logic [33:0] expected;
vector_read_address_add u_add(.clk,.i_base,.i_offset,.i_channel,
    .o_address(address),.o_carry(carry));
assign expected = {2'b00,i_base}+{2'b00,i_offset}+{18'd0,i_channel};
assign equivalent = {carry,address} == expected;
endmodule
''')
    source_paths = [ROOT / SOURCE, Path(__file__).resolve(),
                    ROOT / 'test/vector_dma_address/run_formal.py',
                    ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv',
                    ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    report = {'reference_revision': revision, 'source_sha256': hashes,
              'reference_engine_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'outside_address_addition_unchanged': True, 'input_constraints': None,
              'address_scope': 'All 80 address operand bits; all 34 result bits.',
              'helper_results': {}, 'decode_results': []}
    for mode in ('fpga', 'generic'):
        define = '' if mode == 'fpga' else ' -D ASIC_SYNTHESIS=1'
        script = out / (mode + '.ys')
        sources = ' '.join(shlex.quote(str(p)) for p in (helper_file, proof, model_file))
        script.write_text(f'''read_slang -D SYNTHESIS=1 -D VERIFIC=1 -D YOSYS=1{define} --top address_proof {sources}
prep -top address_proof -flatten
opt -full
sat -verify -prove equivalent 1 -show-inputs -show-outputs
''')
        log = out / (mode + '.log')
        log_hash = execute(script, log)
        assert 'SUCCESS!' in log.read_text()
        report['helper_results'][mode] = {'passed': True, 'log_sha256': log_hash}
        print(json.dumps({'helper': mode, 'passed': True}), flush=True)

    extract = runpy.run_path(str(ROOT / 'test/vector_dma_address/run_formal.py'))['fragment']
    packages = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    for bus, tile in ((32, 16), (64, 16), (128, 16), (32, 3), (64, 32)):
        folder = out / f'bus{bus}_tile{tile}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, source in (('reference', reference), ('current', current)):
            section = extract(source, bus, tile)
            path = folder / (label + '.sv')
            path.write_text(section)
            sources = packages + [path, model_file]
            quoted = ' '.join(shlex.quote(str(p)) for p in sources)
            commands.extend([f'read_slang -D SYNTHESIS=1 -D VERIFIC=1 -D YOSYS=1 --top vector_read_decode {quoted}',
                             'prep -top vector_read_decode -flatten', 'opt -full',
                             'rename vector_read_decode ' + label, 'design -stash ' + label])
        commands.extend(['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current comparison', 'hierarchy -top comparison',
                         'equiv_simple', 'equiv_status -assert'])
        script = folder / 'run.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = folder / 'formal.log'
        log_hash = execute(script, log)
        assert 'Equivalence successfully proven' in log.read_text()
        row = {'bus_width': bus, 'tile': tile, 'passed': True, 'log_sha256': log_hash}
        report['decode_results'].append(row)
        print(json.dumps(row), flush=True)
    assert hashes == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashes}
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
