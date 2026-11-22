"""以共同的符号寄存器输入证明实际加载器的一步状态转换。"""
from pathlib import Path
import argparse, copy, hashlib, json, subprocess, sys
ROOT = Path(__file__).resolve().parents[2]

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
p = argparse.ArgumentParser()
p.add_argument('--models', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--invariant', type=Path, required=True)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
config = json.loads((a.models / 'config.json').read_text())
invariant = json.loads(a.invariant.read_text())
if not invariant['passed'] or invariant['source_sha256'] != config['current_controller_sha256']:
    raise RuntimeError('独立不变量的源文件不匹配')
if not any((all((row[key] == config['parameters'][key] for key in ['SIZE', 'REG_WIDTH', 'COUNT_WIDTH'])) and row['passed'] for row in invariant['profiles'])):
    raise RuntimeError('独立不变量参数未覆盖')
models = {label: json.loads((a.models / f'{label}.json').read_text())['modules'][label] for label in ['reference', 'current']}
saved = {}
owners = {}
for m in models.values():
    if any(('init' in n.get('attributes', {}) for n in m['netnames'].values())):
        raise RuntimeError('初始化状态需要逐位对应检查')
for label, m in models.items():
    ff = {name: c for name, c in m['cells'].items() if 'ff' in c['type'].lower()}
    if any(('latch' in c['type'].lower() or c['type'].startswith('$mem') for c in m['cells'].values())):
        raise RuntimeError('存在未展开的状态单元')
    if set((c['type'] for c in ff.values())) - {'$dff', '$aldff'}:
        raise RuntimeError('未处理的寄存器类型')
    owners[label] = {}
    for name, c in ff.items():
        if int(c['parameters']['CLK_POLARITY'], 2) != 1 or c['connections']['CLK'] != m['ports']['clk']['bits']:
            raise RuntimeError('时钟事件不一致')
        for i, b in enumerate(c['connections']['Q']):
            if not isinstance(b, int) or b in owners[label]:
                raise RuntimeError('寄存器输出重复或为常量')
            owners[label][b] = (name, i)
    saved[label] = set(owners[label])
    assert not saved[label].intersection((b for port in m['ports'].values() if port['direction'] == 'input' for b in port['bits']))
names = set(models['reference']['netnames']) & set(models['current']['netnames'])
names = sorted(names, key=lambda n: (n.startswith('$'), -len(models['reference']['netnames'][n]['bits']), n))
seen = {k: set() for k in models}
selected = []
for name in names:
    values = {label: models[label]['netnames'][name]['bits'] for label in models}
    width = len(values['reference'])
    if width != len(values['current']):
        continue
    for i in range(width):
        bits = {label: values[label][i] for label in models}
        if all((bits[label] in saved[label] and bits[label] not in seen[label] for label in models)):
            selected.append(dict(name=name, bit=i, mapped_bits=bits))
            for label in models:
                seen[label].add(bits[label])
if saved['reference'] != seen['reference']:
    raise RuntimeError('参考状态对应不完整')
extra = saved['current'] - seen['current']
expected = set(models['current']['netnames']['u_ctrl.load_pending_q']['bits'])
if extra != expected or len(extra) != 1:
    raise RuntimeError('新增状态集合不符')
reset_checked = 0
unreset_checked = 0
for row in selected:
    cells = {label: models[label]['cells'][owners[label][row['mapped_bits'][label]][0]] for label in models}
    if cells['reference']['type'] != cells['current']['type']:
        raise RuntimeError('公共状态复位类型不同')
    if cells['reference']['type'] == '$aldff':
        values = {}
        for label, c in cells.items():
            if c['connections']['ALOAD'] != models[label]['ports']['rst_n']['bits'] or int(c['parameters']['ALOAD_POLARITY'], 2) != 0:
                raise RuntimeError('异步复位事件不符')
            value = c['connections']['AD'][owners[label][row['mapped_bits'][label]][1]]
            if value not in ['0', '1', 'x', 'z']:
                raise RuntimeError('异步复位值需要独立检查')
            values[label] = value
        if values['reference'] != values['current']:
            raise RuntimeError('公共状态复位值不同')
        reset_checked += 1
    else:
        unreset_checked += 1
paths = {}
for label, original in models.items():
    m = copy.deepcopy(original)
    next_bit = max([b for c in m['cells'].values() for values in c['connections'].values() for b in values if isinstance(b, int)] + [b for n in m['netnames'].values() for b in n['bits'] if isinstance(b, int)]) + 1
    next_values = {}
    for name, c in m['cells'].items():
        if c['type'] not in ['$dff', '$aldff']:
            continue
        old = c['connections']
        width = len(old['Q'])
        new = list(range(next_bit, next_bit + width))
        next_bit += width
        for q, n in zip(old['Q'], new):
            next_values[q] = n
        if c['type'] == '$dff':
            aa = old['D']
            bb = old['D']
            ss = ['0']
        elif int(c['parameters']['ALOAD_POLARITY'], 2):
            aa = old['D']
            bb = old['AD']
            ss = old['ALOAD']
        else:
            aa = old['AD']
            bb = old['D']
            ss = old['ALOAD']
        c['type'] = '$mux'
        c['parameters'] = {'WIDTH': format(width, '032b')}
        c['port_directions'] = {'A': 'input', 'B': 'input', 'S': 'input', 'Y': 'output'}
        c['connections'] = {'A': aa, 'B': bb, 'S': ss, 'Y': new}
    shared = [row['mapped_bits'][label] for row in selected]
    additional = sorted(extra) if label == 'current' else [next_bit]
    for name, direction, bits in [('formal_shared_state', 'input', shared), ('formal_additional_state', 'input', additional), ('formal_next_state', 'output', [next_values[b] for b in shared])]:
        if name in m['ports']:
            raise RuntimeError('验证端口名称重复')
        m['ports'][name] = {'direction': direction, 'bits': bits}
        m['netnames'][name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
    path = a.out / (label + '.json')
    path.write_text(json.dumps({'modules': {label: m}}, separators=(',', ':')) + '\n')
    paths[label] = path
script = a.out / 'prove.ys'
commands = []
for label in models:
    commands += [f'read_json {paths[label]}', f'hierarchy -top {label}', f'design -stash {label}']
commands += ['design -copy-from reference -as reference reference', 'design -copy-from current -as current current', 'miter -equiv -make_outcmp -make_outputs reference current equivalent', 'prep -top equivalent -flatten', 'opt -full', 'check -assert', 'sat -verify -timeout 60 -set gate_formal_hold_ok 1 -prove trigger 0']
script.write_text('\n'.join(commands) + '\n')
log = a.out / 'proof.log'
with log.open('w') as f:
    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], stdout=f, stderr=subprocess.STDOUT, check=True, timeout=180)
report = {'passed': True, 'common_state_bits': len(selected), 'additional_state_bits': len(extra), 'async_reset_values_compared': reset_checked, 'unreset_shared_state_bits': unreset_checked, 'all_common_state_and_public_outputs': True, 'external_inputs_constrained': False, 'invariant_report': str(a.invariant), 'invariant_report_sha256': digest(a.invariant), 'reference_register_bits': len(saved['reference']), 'current_register_bits': len(saved['current']), 'proof_log_sha256': digest(log), 'models_sha256': {label: digest(a.models / f'{label}.json') for label in models}, 'state_mapping': selected}
(a.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k != 'state_mapping'}), flush=True)
