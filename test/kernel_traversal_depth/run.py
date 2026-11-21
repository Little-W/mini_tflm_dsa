#!/usr/bin/env python3
"""检查遍历计数的无约束组合等价及完整控制器逐周期等价。"""
from pathlib import Path
import argparse, re, shlex, subprocess, json, hashlib, sys
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REL = Path('rtl/npu/loaders/kernel_loader_ctrl.sv')

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def execute(ys, log, needle):
    with log.open('w') as f:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(ys)], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True, timeout=360)
    assert needle in log.read_text(), log
names = ['load_col_in_group', 'load_tile_row', 'load_l2', 'load_repeat']
limits = ['current_group_width', 'tile_rows_total', 'l2_groups_total', 'repeat_total']
lasts = ['last_col_in_group', 'last_tile_row', 'last_l2_group', 'last_repeat']

def model(label, s):
    out = f'module {label} #(parameter CNT_W=29)(input logic [3:0][CNT_W-1:0] values,limits,output logic [4*(CNT_W+1)-1:0] observed);\ntypedef logic [CNT_W-1:0] count_t;\n'
    out += 'count_t ' + ','.join(names + limits) + ';\nlogic ' + ','.join(lasts) + ';\nlogic [3:0][CNT_W-1:0] actual_next;\n'
    for i, (n, lim) in enumerate(zip(names, limits)):
        out += f'assign {n}=values[{i}];\nassign {lim}=limits[{i}];\n'
    if 'traversal_i_value' in s:
        a = s.index('  logic [3:0][CNT_W-1:0] traversal_i_value')
        b = s.index('  function automatic count_t ceil_div_pow2', a)
        out += s[a:b]
        out += 'assign actual_next=traversal_o_next;\n'
    else:
        for i, n in enumerate(names):
            m = re.search(n + '\\s*<=\\s*(' + n + '\\s*\\+.*?);', s)
            assert m, n
            out += f'assign actual_next[{i}]=' + m[1] + ';\n'
    for n in lasts:
        m = re.search('    ' + n + '\\s*=\\s*(.*?);', s, re.S)
        assert m, n
        out += 'assign ' + n + '=' + m[1] + ';\n'
    out += 'assign observed={actual_next,' + ','.join(lasts) + '};\nendmodule\n'
    return out

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', type=Path, default=ROOT / REL)
    p.add_argument('--reference-source', type=Path, default=HERE / 'reference_controller.sv')
    p.add_argument('--out', type=Path, default=ROOT / 'build/kernel_traversal_depth/formal')
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = {'reference': a.reference_source.resolve(), 'candidate': a.candidate.resolve()}
    paths = {}
    source_hashes = {label: digest(path) for label, path in inputs.items()}
    for label, path in inputs.items():
        copied = out / (label + '_controller.sv')
        copied.write_bytes(path.read_bytes())
        paths[label] = copied
    texts = {lab: p.read_text() for lab, p in paths.items()}
    tail = texts['candidate'][texts['candidate'].index('module kernel_count_increment'):]
    sv = out / 'comparison.sv'
    sv.write_text(''.join((model(l, s) for l, s in texts.items())) + 'module comparison #(parameter CNT_W=29)(input logic [3:0][CNT_W-1:0] values,limits,output logic equivalent);\nlogic [4*(CNT_W+1)-1:0] gold,gate;\nreference #(.CNT_W(CNT_W)) u_reference(.values,.limits,.observed(gold));\ncandidate #(.CNT_W(CNT_W)) u_candidate(.values,.limits,.observed(gate));\nassign equivalent=gold==gate;\nendmodule\n' + tail)
    equal_helper = out / 'add_equal.sv'
    equal_helper.write_bytes((ROOT / 'rtl/common/add_equal.sv').read_bytes())
    report = {'passed': False, 'input_assumptions': [], 'source_sha256': {k: digest(p) for k, p in paths.items()}, 'arithmetic': [], 'controller': []}
    for w in [1, 2, 5, 6, 8, 9, 16, 29, 32, 33, 65]:
        ys = out / f'arithmetic_w{w}.ys'
        log = ys.with_suffix('.log')
        ys.write_text(f'read_slang --top comparison -GCNT_W={w} ' + shlex.join([str(sv), str(equal_helper)]) + '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        execute(ys, log, 'SUCCESS!')
        report['arithmetic'].append({'width': w, 'passed': True, 'log_sha256': digest(log)})
        print('ARITHMETIC_PASS', w, flush=True)
    helper_inputs = sorted([p for p in (ROOT / 'rtl/common').iterdir() if p.suffix in ['.v', '.sv']])
    helpers = []
    helper_hashes = {str(path.relative_to(ROOT)): digest(path) for path in helper_inputs}
    for path in helper_inputs:
        copied = out / 'common' / path.name
        copied.parent.mkdir(exist_ok=True)
        copied.write_bytes(path.read_bytes())
        helpers.append(copied)
    report['helper_sha256'] = helper_hashes
    for size, rw, cw in [(16, 32, 29), (1, 8, 1), (4, 16, 16), (16, 32, 33)]:
        name = f'controller_s{size}_r{rw}_c{cw}'
        ys = out / (name + '.ys')
        log = ys.with_suffix('.log')
        commands = []
        for lab, path in paths.items():
            files = ' '.join((shlex.quote(str(p)) for p in [path] + helpers))
            commands += [f'read_slang -D SYNTHESIS=1 --top kernel_loader_ctrl -GSIZE={size} -GREG_WIDTH={rw} -GCOUNT_WIDTH={cw} ' + files, 'prep -top kernel_loader_ctrl -flatten', 'async2sync', 'opt_clean', f'rename kernel_loader_ctrl {lab}', f'design -stash {lab}']
        commands += ['design -copy-from reference -as reference reference', 'design -copy-from candidate -as candidate candidate', 'equiv_make reference candidate equivalent', 'hierarchy -top equivalent', 'equiv_simple -seq 1', 'equiv_induct -seq 3', 'equiv_status -assert']
        ys.write_text('\n'.join(commands) + '\n')
        execute(ys, log, 'Equivalence successfully proven')
        m = re.search('Of those cells (\\d+) are proven and (\\d+) are unproven', log.read_text())
        report['controller'].append({'SIZE': size, 'REG_WIDTH': rw, 'COUNT_WIDTH': cw, 'passed': True, 'equivalent_bits': int(m[1]), 'log_sha256': digest(log)})
        print('CONTROLLER_PASS', name, flush=True)
    assert source_hashes == {label: digest(path) for label, path in inputs.items()}, '验证期间源码发生变化'
    assert helper_hashes == {str(path.relative_to(ROOT)): digest(path) for path in helper_inputs}, '验证期间依赖模块发生变化'
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(out / 'summary.json')
if __name__ == '__main__':
    main()
