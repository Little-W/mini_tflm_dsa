#!/usr/bin/env python3
"""使用官方 DSP48E1 模型比较算术结果与所有操作数状态。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def run_script(folder, stem, commands):
    script = folder / (stem + '.ys')
    script.write_text('\n'.join(commands) + '\n')
    path = folder / (stem + '.log')
    with path.open('w') as log:
        result = subprocess.run([sys.executable,__file__,'--out',str(folder),'--worker',str(script)],
                                stdout=log,stderr=subprocess.STDOUT)
    return result.returncode, path.read_text()


def state_view(original):
    module = copy.deepcopy(original)
    module['ports'].pop('o_result')
    for net in module['netnames'].values():
        net.get('attributes',{}).pop('keep',None)
    return module


def arithmetic_view(original, operation):
    module = copy.deepcopy(original)
    first = max(bit for net in module['netnames'].values() for bit in net['bits']
                if isinstance(bit,int)) + 1
    a = list(range(first,first+16))
    b = list(range(first+16,first+32))
    acc = list(range(first+32,first+64))
    mapping = {}
    for name,value in [('state_a',a+[a[15]]*2),('state_b',b+[b[15]]*14),
                       ('state_a_selected',a),('state_acc',acc)]:
        actual = module['ports'][name]['bits']
        assert len(actual) == len(value)
        for old,new in zip(actual,value):
            if isinstance(old,int):
                assert old not in mapping or mapping[old] == new
                mapping[old] = new
            else:
                assert old == new
    removed = set()
    for name,cell in list(module['cells'].items()):
        bits = cell['connections'].get('Q',[]) if 'dff' in cell['type'] else []
        if any(bit in mapping for bit in bits):
            assert all(bit in mapping for bit in bits)
            removed.update(bits)
            del module['cells'][name]
    assert removed == set(mapping), (len(removed),len(mapping))
    assert not any('dff' in cell['type'] for cell in module['cells'].values())
    for bit,value in zip(module['ports']['i_op']['bits'],[(operation>>i)&1 for i in range(3)]):
        mapping[bit] = str(value)
    module['ports'] = {name:port for name,port in module['ports'].items()
                       if port['direction'] == 'output' and name == 'o_result'}
    for cell in module['cells'].values():
        for name,bits in cell['connections'].items():
            cell['connections'][name] = [mapping.get(bit,bit) for bit in bits]
    for net in module['netnames'].values():
        if any(bit in mapping for bit in net['bits']):
            net.get('attributes',{}).pop('init',None)
        net.get('attributes',{}).pop('keep',None)
        net['bits'] = [mapping.get(bit,bit) for bit in net['bits']]
    for port in module['ports'].values():
        port['bits'] = [mapping.get(bit,bit) for bit in port['bits']]
    for name,bits in [('captured_a',a),('captured_b',b),('captured_acc',acc)]:
        module['ports'][name] = {'direction':'input','bits':bits}
        module['netnames'][name] = {'hide_name':0,'bits':bits,'attributes':{}}
    return module, {'captured_bits_replaced':len(removed),'operation':operation}


def model_snapshot(out):
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
    model = re.sub(r'\bspecify\b.*?\bendspecify\b','',model,flags=re.S)
    path = out / 'DSP48E1.sv'
    path.write_text(model + '\n')
    return path, hashlib.sha256(library.read_bytes()).hexdigest()


def wrapper(dsp):
    state_a = 'u_impl.g_dsp.u_dsp.Br2' if dsp else "18'($signed(u_impl.operand_a_q))"
    state_b = 'u_impl.g_dsp.u_dsp.Ar2' if dsp else "30'($signed(u_impl.g_generic.operand_b_q))"
    return f'''module pe_state (
      input logic clk, i_en,
      input logic [2:0] i_op,
      input logic signed [15:0] i_a, i_b,
      input logic signed [31:0] i_acc,
      output logic signed [31:0] o_result,
      output logic [17:0] state_a,
      output logic [29:0] state_b,
      output logic [15:0] state_a_selected,
      output logic [31:0] state_acc
    );
      registered_vector_pe #(.p_use_dsp(1'b{int(dsp)})) u_impl (.*);
      assign state_a = {state_a};
      assign state_b = {state_b};
      assign state_a_selected = u_impl.operand_a_q;
      assign state_acc = u_impl.operand_acc_q;
    endmodule
    '''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--worker',type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    source = ROOT / 'rtl/npu/conv/vector_pe.sv'
    snapshot = out / 'vector_pe.sv'
    snapshot.write_bytes(source.read_bytes())
    model, library_sha256 = model_snapshot(out)
    modules = {}
    for label,dsp in [('reference',False),('candidate',True)]:
        path = out / (label + '.sv')
        path.write_text(wrapper(dsp))
        commands = ['read_slang --top pe_state -D YOSYS=1 -D VERIFIC=1 ' +
                    ' '.join(shlex.quote(str(p)) for p in [path,snapshot,model]),
                    'prep -top pe_state -flatten','memory_map','opt -full','wreduce','opt -full',
                    'write_json ' + str(out / (label + '.json'))]
        code,log = run_script(out,label+'_elaborate',commands)
        if code:
            raise RuntimeError(log[-6000:])
        modules[label] = json.loads((out / (label + '.json')).read_text())['modules']['pe_state']
    report = {'source_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
              'primitive_library_sha256':library_sha256,'input_constraints':None,
              'compared_semantic_state_bits':96,'compared_result_bits':32,
              'method':'Prove actual capture state, then compare its combinational consumers for every operation encoding.',
              'runs':[]}
    for stage in ['state'] + list(range(8)):
        stem = 'state' if stage == 'state' else f'operation_{stage}'
        commands = []
        for label in ['reference','candidate']:
            if stage == 'state':
                selected = state_view(modules[label])
            else:
                selected,_ = arithmetic_view(modules[label],stage)
            selected['attributes']['top'] = '1'
            path = out / (stem + '_' + label + '.json')
            path.write_text(json.dumps({'modules':{label:selected}}))
            commands += ['read_json ' + str(path),'opt -full','wreduce','opt -full',
                         'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate']
        if stage == 'state':
            commands += ['equiv_make reference candidate comparison','hierarchy -top comparison',
                         'equiv_struct -fwd -icells','equiv_simple','equiv_induct -seq 2',
                         'equiv_status -assert']
        else:
            commands += ['miter -equiv -flatten reference candidate comparison','hierarchy -top comparison',
                         'opt -full','wreduce','opt -full','sat -verify -prove trigger 0 -show-inputs -show-outputs']
        code,log = run_script(out,stem,commands)
        passed = code == 0 and ('Equivalence successfully proven!' in log if stage == 'state' else 'SUCCESS!' in log)
        result = {'stage':stem,'passed':passed}
        report['runs'].append(result)
        print(json.dumps(result),flush=True)
        if not passed:
            print(log[-10000:])
            raise SystemExit(1)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report,indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
