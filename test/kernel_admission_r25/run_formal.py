#!/usr/bin/env python3
"""证明空闲条件下的请求关系、完整接收输出及原核加载状态。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from model import ROOT, REFERENCE, KERNEL, SOURCES, connected, digest, extensions, load, source


def run(folder, name, commands, expected):
    script, log = folder / (name + '.ys'), folder / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, timeout=300, check=True)
    content = log.read_text()
    assert expected in content, str(log)
    return {'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--connected-only', action='store_true')
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    versions = {'reference': {p: source(p, REFERENCE) for p in SOURCES},
                'current': {p: source(p) for p in SOURCES}}
    hashes = {name: {str(p): hashlib.sha256(text.encode()).hexdigest() for p, text in data.items()}
              for name, data in versions.items()}
    report = {'passed': False, 'reference_commit': REFERENCE, 'source_sha256': hashes,
              'inputs_constrained': False, 'state_constraints': False,
              'extension_check': extensions(versions['reference'], versions['current']),
              'connected': [], 'kernel': []}
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = folder / 'models.sv'
    model.write_text('\n\n'.join(re.sub(r'\bspecify\b.*?\bendspecify\b', '',
        re.search(r'^module '+name+r'\b.*?^endmodule', library.read_text(), re.M|re.S)[0], flags=re.S)
        for name in ('LUT1','LUT2','LUT3','LUT4','LUT5','LUT6','LUT6_2','MUXF7','MUXF8','DSP48E1')) + '\n')
    report['official_library_sha256'] = digest(library)
    report['official_models_sha256'] = digest(model)
    for label, data in versions.items():
        (folder / (label + '.sv')).write_text(connected(data))
    cases = [(32,16,fpga,quant,gating) for fpga in (0,1) for quant in (0,1) for gating in (0,1)]
    cases += [(8,4,0,1,1),(8,4,1,1,1),(64,16,0,1,1),(64,16,1,1,1)]
    for width, size, fpga, quant, gating in cases:
        name = f'connected_w{width}_s{size}_f{fpga}_q{quant}_g{gating}'
        commands = []
        for label in versions:
            mode = '-DSYNTHESIS=1 -DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1'
            commands += [f'read_slang {mode} --top admission_connected -GREG_WIDTH={width} -GSIZE={size} '
                f'-GENABLE_QUANT_CLIENT={quant} -GENABLE_CLOCK_GATING={gating} {folder/(label+".sv")} {model}',
                'prep -top admission_connected -flatten', 'check -assert',
                f'rename admission_connected {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -flatten reference current miter', 'hierarchy -top miter',
                     'sat -verify -prove trigger 0 -show-inputs -show-outputs']
        result = run(folder, name, commands, 'SAT proof finished - no model found: SUCCESS!')
        report['connected'].append({'reg_width': width, 'size': size, 'fpga': bool(fpga),
            'quantization': quant, 'clock_gating': gating, 'output_bits': 13, **result})
        print(name, 'PASS', flush=True)
    # 查找表的每一项均与六输入表达式比较。
    init = int(re.search(r"LUT6 #\(\.INIT\(64'h([0-9a-f_]+)\)\) u_admission", versions['current'][KERNEL])[1].replace('_',''),16)
    for value in range(64):
        state, flush, request, mode, ready, config = [(value >> i) & 1 for i in range(6)]
        expected = not state and not flush and request and (not mode or (ready and not config))
        assert ((init >> value) & 1) == int(expected)
    report['lut_truth_table_cases'] = 64
    if not args.connected_only:
        original = load('r25_kernel_complete', 'test/kernel_request_idle/run_formal.py')
        state_tools = load('r25_state_tools', 'test/npu_admission_r22/extract.py')
        for dependency in original.DEPENDENCIES:
            assert source(dependency, REFERENCE) == source(dependency)
        report['dependency_sha256'] = {str(p): digest(ROOT/p) for p in original.DEPENDENCIES}
        complete = folder / 'kernel'
        complete.mkdir(exist_ok=True)
        for label, data in versions.items():
            (complete / (label + '.sv')).write_text(data[KERNEL])
        for size, count, bus, fpga in ((4,8,32,False),(16,32,64,False),
                                     (16,29,32,True),(16,29,64,True)):
            name = f'kernel_s{size}_c{count}_b{bus}_f{int(fpga)}'
            observations = {}
            for label in versions:
                mode = '-DSYNTHESIS=1 -DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1'
                inputs = ' '.join(str(p) for p in (complete/(label+'.sv'), *(ROOT/p for p in original.DEPENDENCIES), model))
                net = complete / (name + '_' + label + '.json')
                commands = [f'read_slang {mode} --top kernel_loader -GSIZE={size} -GCOUNT_WIDTH={count} '
                            f'-GBUS_WIDTH={bus} -GDATA_WIDTH=16 {inputs}',
                            'prep -top kernel_loader -flatten', 'memory_map', 'opt_clean']
                if label == 'current':
                    commands += ['delete -output kernel_loader/o_admission_request', 'opt_clean']
                commands += [f'write_json {net}']
                run(complete, name + '_' + label, commands, 'Executing JSON backend.')
                data = json.loads(net.read_text())
                nets = data['modules']['kernel_loader']['netnames']
                for signal in list(nets):
                    if signal.startswith(('admission_', 'g_admission_request_', 'o_admission_request')):
                        del nets[signal]
                net.write_text(json.dumps(data) + '\n')
                observations[label] = state_tools.retain_public_and_state(net, 'kernel_loader')
            assert observations['reference'] == observations['current']
            commands = []
            for label in versions:
                commands += [f'read_json {complete/(name+"_"+label+".json")}', 'prep -top kernel_loader',
                             'async2sync', f'rename kernel_loader {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                         'equiv_induct -seq 2', 'equiv_status -assert']
            result = run(complete, name, commands, 'Equivalence successfully proven')
            count_proven = int(re.search(r'Of those cells (\d+) are proven and 0 are unproven',
                                         (complete / (name + '.log')).read_text())[1])
            report['kernel'].append({'size': size, 'count_width': count, 'bus_width': bus,
                'fpga': fpga, 'equivalent_bits': count_proven, **observations['current'], **result})
            print(name, 'PASS', count_proven, flush=True)
    assert hashes['current'] == {str(p): digest(ROOT/p) for p in SOURCES}
    report['passed'] = True
    report['script_sha256'] = {str(p.relative_to(ROOT)): digest(p) for p in (Path(__file__), Path(__file__).with_name('model.py'))}
    (folder / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(folder / 'summary.json', flush=True)


if __name__ == '__main__':
    main()
