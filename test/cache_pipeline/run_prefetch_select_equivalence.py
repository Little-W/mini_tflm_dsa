#!/usr/bin/env python3
"""对预取队列的全部位置映射、有效位、代次匹配位和队首编码证明选择结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/cache/conv_read_cache.sv'


def selection_block(source):
    markers = ('  // 按逻辑顺序并行判断代次', '  // 从队首开始循环查找第一个代次匹配项')
    start = next(source.index(marker) for marker in markers if marker in source)
    end = source.index('  assign lookup_addr =', start)
    return source[start:end]


def selection_declarations(source):
    start = source.index('  logic [PF_DEPTH-1:0] pf_slot_valid,')
    end = source.index('  logic offer_valid,', start)
    return source[start:end]


def helper(source, name):
    body = selection_block(source)
    declarations = selection_declarations(source).replace('pf_slot_valid, ', '')
    return f'''module {name} (
    input logic [2:0] pf_head,
    input logic [7:0] pf_slot_valid, pf_epoch_matches,
    input logic [2:0] pf_slot_map_q [8],
    output logic [2:0] pf_pick_comb, pf_read_slot
);
    localparam int PF_DEPTH=8, PF_AW=3;
{declarations}
{body}
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='c64772b')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    normalized = current.replace(selection_block(current), selection_block(reference))
    normalized = normalized.replace(selection_declarations(current), selection_declarations(reference))
    if normalized != reference:
        raise ValueError('Changes outside the selection block remain uncovered')
    outputs = ['pf_pick_comb', 'pf_read_slot']
    declarations = []
    instances = []
    for side in ('reference', 'current'):
        declarations.append(f'logic [2:0] {side}_pf_pick_comb, {side}_pf_read_slot;')
        ports = ','.join(f'.{signal}({side}_{signal})' for signal in outputs)
        instances.append(f'{side}_select u_{side} ({ports}, .*);')
    old = ','.join('reference_' + signal for signal in outputs)
    new = ','.join('current_' + signal for signal in outputs)
    rtl = out / 'prefetch_select.sv'
    rtl.write_text(helper(reference, 'reference_select') + helper(current, 'current_select') + f'''
module prefetch_select_proof (
    input logic [2:0] pf_head,
    input logic [7:0] pf_slot_valid, pf_epoch_matches,
    input logic [2:0] pf_slot_map_q [8],
    output logic equivalent
);
{chr(10).join(declarations)}
{chr(10).join(instances)}
assign equivalent = {{{old}}} == {{{new}}};
endmodule
''')
    script = out / 'proof.ys'
    script.write_text('read_slang --top prefetch_select_proof ' + shlex.quote(str(rtl)) + '\n' +
                      'prep -top prefetch_select_proof -flatten\n' +
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    log = out / 'proof.log'
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
        raise RuntimeError('SAT equivalence did not complete')
    sha = lambda value: hashlib.sha256(value).hexdigest()
    result = {'passed': True, 'reference_ref': args.reference_ref, 'input_bits': 43,
              'equivalent_output_bits': 6, 'inputs_constrained': False,
              'remaining_module_body_identical': True,
              'source_sha256': sha(current.encode()), 'reference_sha256': sha(reference.encode()),
              'proof_source_sha256': sha(rtl.read_bytes()), 'proof_log_sha256': sha(log.read_bytes()),
              'outputs': outputs}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PREFETCH_SELECT_EQUIVALENCE_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
