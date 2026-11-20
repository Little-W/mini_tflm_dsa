#!/usr/bin/env python3
"""证明加载请求接收与预取空闲选择的全部输入关系和完整加载器状态。"""
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
SOURCE = Path('rtl/npu/loaders/kernel_loader.sv')
DEPENDENCIES = tuple(Path(path) for path in (
    'rtl/npu/loaders/kernel_loader_ctrl.sv',
    'rtl/npu/loaders/kernel_loader_buffer.sv',
    'rtl/common/regfile.v', 'rtl/common/add_equal.sv', 'rtl/common/add3_equal.sv'))
PROOF = '''module kernel_request_idle_proof #(parameter bit p_use_lut=1'b0) (
    input logic request, granted, quiescent,
    output logic equivalent
);
    logic start_result, idle_result;
    kernel_request_idle #(.p_use_lut(p_use_lut)) dut (
        .i_request(request), .i_granted(granted), .i_quiescent(quiescent),
        .o_start(start_result), .o_idle(idle_result)
    );
    assign equivalent = start_result == (request && granted) &&
        idle_result == (quiescent && !(request && granted));
endmodule
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8bd4b00b')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = (SOURCE, *DEPENDENCIES)
    hashes = {str(path): digest(ROOT/path) for path in paths}
    source_files = {}
    reuse_sources = args.resume
    for label in ('reference', 'current'):
        path = out/(label+'.sv')
        data = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT) \
            if label == 'reference' else (ROOT/SOURCE).read_bytes()
        reuse_sources &= path.exists() and path.read_bytes() == data
        path.write_bytes(data)
        source_files[label] = path
    for dependency in DEPENDENCIES:
        original = read_rtl_source(f'{args.reference}:{dependency}', cwd=ROOT)
        assert original == (ROOT/dependency).read_bytes()
    proof = out/'selection_proof.sv'
    proof.write_text(PROOF)
    import pyosys
    library = Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model = out/'xilinx_models.sv'
    model_text = '\n\n'.join(re.search(r'^module '+name+r'\b.*?^endmodule',
        library.read_text(), re.M|re.S)[0] for name in ('LUT1', 'LUT6', 'LUT6_2', 'MUXF7', 'MUXF8', 'DSP48E1'))
    model_text = re.sub(r'\bspecify\b.*?\bendspecify\b', '', model_text, flags=re.S)+'\n'
    reuse_sources &= model.exists() and model.read_text() == model_text
    model.write_text(model_text)
    report = {'passed': False, 'reference': args.reference, 'source_sha256': hashes,
              'reference_sha256': digest(source_files['reference']),
              'inputs_constrained': False, 'storage_implementation_identical': True,
              'primitive_library_sha256': digest(library), 'primitive_model_sha256': digest(model),
              'selection': [], 'loader': []}

    def run(name, commands, success):
        script, log = out/(name+'.ys'), out/(name+'.log')
        script_text = '\n'.join(commands)+'\n'
        if reuse_sources and script.exists() and script.read_text() == script_text and log.exists():
            content = log.read_text()
            if success in content:
                return content, digest(log)
        script.write_text(script_text)
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=300)
        content = log.read_text()
        assert success in content
        return content, digest(log)

    for fpga in (False, True):
        command = f'read_slang -D ASIC_SYNTHESIS=1 --top kernel_request_idle_proof -Gp_use_lut={int(fpga)} '
        command += ' '.join(shlex.quote(str(path)) for path in (source_files['current'], model, proof))
        _, log_hash = run('selection_'+str(int(fpga)), [command,
            'prep -top kernel_request_idle_proof -flatten',
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs'],
            'SAT proof finished - no model found: SUCCESS!')
        report['selection'].append({'fpga': fpga, 'input_bits': 3, 'passed': True,
                                     'log_sha256': log_hash})

    for size, count, bus, fpga in ((4, 8, 32, False), (16, 32, 64, False),
                                   (16, 29, 32, True), (16, 29, 64, True)):
        commands = []
        mode = '-D SYNTHESIS=1 -D XILINX_FPGA=1' if fpga else '-D ASIC_SYNTHESIS=1'
        for label, source in source_files.items():
            inputs = [source, *(ROOT/path for path in DEPENDENCIES), model]
            commands += [f'read_slang {mode} --top kernel_loader -GSIZE={size} -GCOUNT_WIDTH={count} '
                         f'-GBUS_WIDTH={bus} -GDATA_WIDTH=16 '+
                         ' '.join(shlex.quote(str(path)) for path in inputs),
                         'prep -top kernel_loader -flatten', 'memory_map', 'async2sync', 'opt_clean']
            if fpga:
                # 真值表展开的组合中间线使用私有名称，实际状态和接口继续完整比较。
                commands += ['rename -hide w:*.s1 w:*.s2 w:*.s3 w:*.s4 w:*.s5 w:*.s5_0 w:*.s5_1']
            commands += [f'rename kernel_loader {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        name = f'loader_s{size}_c{count}_b{bus}_f{int(fpga)}'
        content, log_hash = run(name, commands, 'Equivalence successfully proven')
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', content)
        assert match and int(match[2]) == 0
        row = {'size': size, 'count_width': count, 'bus_width': bus, 'fpga': fpga,
               'passed': True, 'equivalent_bits': int(match[1]), 'log_sha256': log_hash}
        report['loader'].append(row)
        print(json.dumps(row), flush=True)
    assert hashes == {str(path): digest(ROOT/path) for path in paths}
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
