#!/usr/bin/env python3
"""验证累加存储串行读取共享的控制条件、完整下一状态和公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PHASE = '''
  logic [3:0] proof_opcode, proof_cfg_opcode;
  assign proof_opcode = c.op;
  assign proof_cfg_opcode = cfg.op;
  assign proof_phase_legal =
      ((state!=QUANT_STREAM) || (proof_opcode==DW_S8)) &&
      ((state!=AVG_START && state!=AVG_WAIT && state!=AVG_POWER_STORE) || (proof_opcode==AVGPOOL_S8)) &&
      ((state!=VECTOR_REDUCE) || (proof_opcode!=DW_S8 && proof_opcode!=AVGPOOL_S8 && proof_opcode!=SOFTMAX_S8));
'''
ASSERTIONS = '''
  always_comb begin
    if (state==QUANT_STREAM) assert(c.op==DW_S8);
    if (state==AVG_START || state==AVG_WAIT || state==AVG_POWER_STORE) assert(c.op==AVGPOOL_S8);
    if (state==VECTOR_REDUCE) assert(c.op!=DW_S8 && c.op!=AVGPOOL_S8 && c.op!=SOFTMAX_S8);
  end
'''


def modified_source(source, label, control=False):
    top = 'acc_' + label
    result = source.replace('module vector_engine #(', 'module '+top+' #(', 1)
    position = result.index('\n);')
    result = result[:position] + ',\n  output logic proof_phase_legal' + result[position:]
    position = result.index('endmodule')
    result = result[:position] + PHASE + (ASSERTIONS if control else '') + result[position:]
    return top, result


def source_list(design):
    files = [ROOT/'rtl/npu/conv/conv_im2col_pkg.sv', ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    files += [path for path in sorted((ROOT/'rtl/npu/conv').glob('*.sv'))
              if path not in files and path.name != 'vector_engine.sv']
    return files + [ROOT/'rtl/common/pseudo_dual_port_ram.v', ROOT/'rtl/common/REGFILE.v',
                    ROOT/'rtl/common/add_equal.sv', design]


def command(args, log):
    with log.open('w') as stream:
        result = subprocess.run(list(map(str, args)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(str(log)+'\n'+log.read_text()[-6000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='b8b34d5')
    parser.add_argument('--bus-width', type=int, choices=(32,64), default=64)
    parser.add_argument('--tile', type=int, default=16)
    parser.add_argument('--pes', type=int, default=8)
    parser.add_argument('--worker-ys', type=Path)
    args = parser.parse_args()
    if args.worker_ys:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker_ys)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = ROOT/'rtl/npu/conv/vector_engine.sv'
    candidate = source_path.read_text()
    reference = subprocess.check_output(['git','show',args.reference_rev+':rtl/npu/conv/vector_engine.sv'], cwd=ROOT, text=True)
    options = f'-DASIC_SYNTHESIS -GTILE={args.tile} -GPE_COUNT={args.pes} -GBUS_WIDTH={args.bus_width}'
    identities = {'reference_rev':args.reference_rev, 'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),
                  'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
                  'tile':args.tile, 'pe_count':args.pes, 'bus_width':args.bus_width}
    for label, source, control in [('reference',reference,False), ('candidate',candidate,False), ('control',candidate,True)]:
        top, body = modified_source(source,label,control)
        path = out/(label+'.sv')
        path.write_text(body)
        script = f'read_slang --top {top} {options} '+ ' '.join(shlex.quote(str(p)) for p in source_list(path))+'\n'
        if control:
            script += f'delete -output {top}/w:*\nprep -top {top} -flatten\nasync2sync\nsetattr -unset keep\nopt -full\nchformal -lower\nopt_clean\n'
            script += f'rename -top vector_engine_control_proof\nwrite_rtlil {out}/control.il\nwrite_json {out}/control_cells.json\n'
        else:
            script += f'prep -top {top} -flatten\nmemory_map\ndffunmap\nopt_clean\nwrite_json {out}/{label}.json\n'
        script_path = out/(label+'.ys')
        script_path.write_text(script)
        command([sys.executable,__file__,'--out',out,'--worker-ys',script_path],out/(label+'.log'))
    command([sys.executable,HERE/'control_worker.py',out],out/'control_proof.log')
    command([sys.executable,HERE/'transition_worker.py',out],out/'transition_proof.log')
    identities['control'] = json.loads((out/'control_summary.json').read_text())
    identities['transition'] = json.loads((out/'transition_summary.json').read_text())
    identities['passed'] = identities['control']['passed'] and identities['transition']['passed']
    if source_path.read_text() != candidate:
        raise RuntimeError('RTL changed during verification')
    (out/'summary.json').write_text(json.dumps(identities,indent=2)+'\n')
    print(json.dumps(identities),flush=True)


if __name__ == '__main__':
    main()
