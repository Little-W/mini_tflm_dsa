#!/usr/bin/env python3
"""证明权重加载器描述符比较的全部状态、公开输出和三项模加法等式。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/npu/loaders/kernel_loader.sv'), Path('rtl/npu/loaders/kernel_loader_ctrl.sv')]
PROFILES = [(4, 8, 32), (16, 16, 32), (16, 29, 64)]
MITER = '''module sum_equal_proof #(parameter int p_width = 32) (
    input logic [p_width-1:0] a, b, c, target,
    output logic equivalent
);
    logic [p_width-1:0] result;
    logic equal;
    add3_equal #(.p_width(p_width)) dut (
        .i_a(a), .i_b(b), .i_c(c), .i_target(target), .o_equal(equal)
    );
    assign result = a + b + c;
    assign equivalent = (equal == (result == target));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='7598ae9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common = sorted(path for path in (ROOT / 'rtl/common').glob('*') if path.suffix in ('.v', '.sv'))
    common.append(ROOT / 'rtl/npu/loaders/kernel_loader_buffer.sv')
    snapshots = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for source in SOURCES:
            path = folder / source.name
            text = (subprocess.check_output(['git', 'show', f'{args.reference_rev}:{source}'], cwd=ROOT, text=True)
                    if label == 'reference' else (ROOT / source).read_text())
            if source.name == 'kernel_loader_ctrl.sv':
                # 运行阶段实际使用的步长作为组合观察点，配置阶段不消费该值。
                register = 'group_addr_step' if label == 'reference' else 'group_addr_step_q'
                observation = ("\n  (* keep *) wire [REG_WIDTH-1:0] group_addr_step_active =\n"
                               f"      (state == S_RUN) ? {register} : '0;\n")
                original_add = f'group_base_addr + {register};'
                assert text.count(original_add) == 1
                text = text.replace(original_add, 'group_base_addr + group_addr_step_active;', 1)
                declaration_marker = '  function automatic count_t ceil_div_pow2'
                assert text.count(declaration_marker) == 1
                text = text.replace(declaration_marker, observation + '\n' + declaration_marker, 1)
            path.write_text(text)
            snapshots[label].append(path)
    miter = out / 'sum_equal_proof.sv'
    miter.write_text(MITER)
    report = {'reference_rev': args.reference_rev, 'inputs_constrained': False,
              'source_sha256': {str(path): hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                for path in SOURCES},
              'dependency_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in common},
              'loader_profiles': [], 'sum_profiles': []}

    def run(name, commands, expected):
        script, log_path = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log_path.open('w') as stream:
            process = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                      '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT)
        log = log_path.read_text()
        if process.returncode != 0 or expected not in log:
            raise RuntimeError(f'Formal comparison did not complete: {log_path}')
        return log, hashlib.sha256(log_path.read_bytes()).hexdigest()

    for width in (1, 4, 16, 32, 64):
        sources = [ROOT / 'rtl/common/add3_equal.sv', ROOT / 'rtl/common/add_equal.sv', miter]
        commands = [f'read_slang --top sum_equal_proof -Gp_width={width} ' +
                    ' '.join(shlex.quote(str(path)) for path in sources),
                    'prep -top sum_equal_proof -flatten',
                    'sat -verify -prove equivalent 1 -show-inputs -show-outputs']
        _, log_hash = run(f'sum_w{width}', commands, 'SAT proof finished - no model found: SUCCESS!')
        report['sum_profiles'].append({'width': width, 'unconstrained_input_bits': 4 * width,
                                       'passed': True, 'log_sha256': log_hash})
        print(json.dumps(report['sum_profiles'][-1]), flush=True)
    for size, count, bus in PROFILES:
        commands = []
        for label in ('reference', 'current'):
            paths = snapshots[label] + common
            commands += [f'read_slang --top kernel_loader -GSIZE={size} -GCOUNT_WIDTH={count} '
                         f'-GBUS_WIDTH={bus} -GDATA_WIDTH=16 ' + ' '.join(shlex.quote(str(p)) for p in paths),
                         'prep -top kernel_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename kernel_loader {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current', 'equiv_make reference current equivalent',
                     'hierarchy -top equivalent', 'equiv_simple -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        log, log_hash = run(f'loader_s{size}_c{count}_b{bus}', commands, 'Equivalence successfully proven')
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log)
        report['loader_profiles'].append({'size': size, 'count_width': count, 'bus_width': bus,
                                          'passed': True, 'equivalent_bits': int(match.group(1)),
                                          'log_sha256': log_hash})
        print(json.dumps(report['loader_profiles'][-1]), flush=True)
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    for source in SOURCES:
        assert hashlib.sha256((ROOT / source).read_bytes()).hexdigest() == report['source_sha256'][str(source)]
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
