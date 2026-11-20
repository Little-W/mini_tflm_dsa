#!/usr/bin/env python3
"""逐位证明替换来源的优先级和保持行为，并核对模块其余内容。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from tag_port_equivalence import normalize_source as normalize_tag_source

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/cache/conv_read_cache.sv'
NOTE = '      // 同一来源标记共用更新使能，填充和提示分别覆盖较早的命中更新。\n'


def state_block(source):
    start = source.index('    for(genvar metadata_set=0;')
    start = source.index('      always_ff @(posedge clk)', start)
    end = source.index('    end\n  end\n', start)
    return source[start:end]


def helper_declaration(source):
    match = re.search(r'      logic rank_hit_write;\n      assign rank_hit_write = [^;]+;\n', source)
    return match.group(0) if match else ''


def helper(source, name):
    body = state_block(source).replace('always_ff @(posedge clk)', '')
    body = body.replace('rank_source[metadata_set]', 'next_state').replace('<=', '=')
    return f'''module {name} (
    input logic [1:0] current_state,
    input logic rst_n, metadata_enable, hit_write, hint_write, fill_write,
    input logic windowed_q, hint_valid,
    output logic [1:0] next_state
);
{helper_declaration(source)}
always_comb begin
    next_state = current_state;
{body}
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='b93cad0')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT, text=True)
    shared_tag_ports = '    // 预取接收时读取新描述地址' in current
    normalized = normalize_tag_source(current, reference) if shared_tag_ports else current
    normalized = normalized.replace(state_block(current), state_block(reference))
    normalized = normalized.replace(helper_declaration(current), '').replace(NOTE, '')
    if normalized != reference:
        raise ValueError('Additional module changes require verification')
    rtl = out / 'rank_source.sv'
    rtl.write_text(helper(reference, 'reference_source') + helper(current, 'current_source') + '''
module rank_source_proof (
    input logic [1:0] current_state,
    input logic rst_n, metadata_enable, hit_write, hint_write, fill_write,
    input logic windowed_q, hint_valid,
    output logic equivalent
);
logic [1:0] reference_next, current_next;
reference_source u_reference (.next_state(reference_next), .*);
current_source u_current (.next_state(current_next), .*);
assign equivalent = reference_next == current_next;
endmodule
''')
    script = out / 'proof.ys'
    script.write_text('read_slang --top rank_source_proof ' + shlex.quote(str(rtl)) + '\n' +
                      'prep -top rank_source_proof -flatten\n' +
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    log = out / 'proof.log'
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
        raise RuntimeError('Source state comparison is incomplete')
    tag_result = None
    if shared_tag_ports:
        subprocess.run([sys.executable, str(ROOT / 'test/cache_storage/tag_port_equivalence.py'),
                        '--out', str(out / 'tag_ports')], check=True)
        tag_result = json.loads((out / 'tag_ports/summary.json').read_text())
        if not tag_result['passed'] or tag_result['source_sha256'] != hashlib.sha256(current.encode()).hexdigest():
            raise RuntimeError('Tag-port comparison is incomplete')
    sha = lambda data: hashlib.sha256(data).hexdigest()
    result = {'passed': True, 'reference_ref': args.reference_ref, 'input_bits': 9,
              'output_bits': 2, 'inputs_constrained': False, 'remaining_module_body_identical': True,
              'source_sha256': sha(current.encode()), 'reference_sha256': sha(reference.encode()),
              'proof_source_sha256': sha(rtl.read_bytes()), 'proof_log_sha256': sha(log.read_bytes()),
              'priority': ['fill', 'hint', 'qualified hit', 'hold'],
              'coverage': 'Every source encoding, every write-event combination, reset gating and configuration gating.',
              'tag_port_proof': tag_result}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('RANK_SOURCE_EQUIVALENCE_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
