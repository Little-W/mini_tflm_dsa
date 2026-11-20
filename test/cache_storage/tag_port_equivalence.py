#!/usr/bin/env python3
"""证明预取标签读地址共享的同步周期，并核对标签消费者及存储写入。"""
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
SOURCE = 'rtl/npu/dma/cache/conv_read_cache.sv'
STORAGE = 'rtl/common/regfile.v'
TAGS = ('lookup_tag', 'pf_tag', 'incoming_tag', 'next_tag', 'hint_lookup_tag')


def read_assignments(source):
    start = source.index('    assign tags_i_rd_en =')
    end = source.index('    assign metadata_i_rd_en =', start)
    return source[start:end]


def read_declarations(source):
    return '\n'.join(line for line in source.splitlines()
                     if re.match(r'    logic .*\b(?:tags_i_rd_en|tags_i_rd_addr|tags_o_rd_data|incoming_live_q)\b', line)) + '\n'


def tag_instance(source):
    start = source.index('    regfile #(', source.index('    // 预取接收时读取新描述地址')
                         if '    // 预取接收时读取新描述地址' in source
                         else source.index('    // 标签共用写入地址'))
    end = source.index('    );', start) + len('    );')
    return source[start:end]


def fresh_state(source):
    pattern = r'  always_ff @\(posedge clk or negedge rst_n\) begin\n    if \(!rst_n\) offer_fresh_q.*?\n  end\n'
    return re.search(pattern, source, re.S).group(0)


def normalize_source(current, reference):
    result = current.replace(read_assignments(current), read_assignments(reference))
    for line in read_declarations(current).splitlines(keepends=True):
        result = result.replace(line, '')
    result = result.replace('    localparam int p_tag_width = 32-LB;\n',
                            '    localparam int p_tag_width = 32-LB;\n' +
                            '    logic [31:LB] incoming_live_q, next_live_q, incoming_hold_q, next_hold_q;\n')
    result = result.replace('    logic metadata_i_rd_en;\n',
                            '    logic [6:0] tags_i_rd_en;\n'
                            '    logic [6:0][SI-1:0] tags_i_rd_addr;\n'
                            '    logic [6:0][p_tag_width-1:0] tags_o_rd_data;\n'
                            '    logic metadata_i_rd_en;\n')
    result = result.replace(tag_instance(current), tag_instance(reference))
    return result.replace('    // 预取接收时读取新描述地址，其余周期读取已保存地址，标签保持原有同步周期。',
                          '    // 标签共用写入地址，各用途按原有周期同步读取。')


def audit_consumers(source):
    consumers = {
        'lookup_tag': 'if (lookup_ready && valid_lookup[w] && lookup_tag[w]==lookup_addr[31:LB]) begin',
        'pf_tag': 'if (pf_lookup_ready && valid_prefetch[w] && pf_tag[w]==pf_addr[31:LB]) pf_hit_raw=1;',
        'incoming_tag': 'if (valid_incoming[w] && incoming_tag[w]==offer_addr_q[31:LB]) pf_duplicate=1;',
        'next_tag': 'if (valid_next[w] && next_tag[w]==offer_next_addr_q[31:LB]) pf_duplicate=1;',
        'hint_lookup_tag': 'valid_hint[metadata_way] && hint_lookup_tag[metadata_way] == hint_tag;'
    }
    for name, statement in consumers.items():
        if statement not in source:
            raise ValueError('A tag consumer changed: ' + name)
    valid = re.search(r'assign valid_active\[read_port\] = (.*?);', source, re.S).group(1)
    if not valid.startswith('configured && !clearing && valid_o_rd_data[read_port][0] &&'):
        raise ValueError('Tag validity qualification changed')
    remaining = source.replace(read_assignments(source), '')
    remaining = re.sub(r'^\s*logic \[WAYS-1:0\]\[31:LB\] [^;]+;\n', '', remaining, flags=re.M)
    for line in remaining.splitlines():
        if not re.search(r'\b(?:' + '|'.join(TAGS) + r')\b', line):
            continue
        if line.strip() in consumers.values():
            continue
        if line.strip() == 'hint_lookup_tag[metadata_way]==hint_tag;':
            continue
        raise ValueError('An additional tag consumer requires verification: ' + line.strip())
    if re.findall(r'\bconfigured\s*<=\s*([^;]+);', source) != ['0', '1']:
        raise ValueError('Configuration-state lifetime changed')
    for kind, port in [('lookup', 0), ('prefetch', 1), ('incoming', 2), ('next', 3), ('hint', 5)]:
        if f'assign valid_{kind}[metadata_way] = valid_active[{port}];' not in source:
            raise ValueError('A validity consumer changed: ' + kind)


def storage_read_body(storage):
    match = re.search(r'            always_ff @\(posedge clk\) begin\n'
                      r'                if \(i_rd_en\[port_index\]\) begin\n'
                      r'                    o_rd_data\[port_index\] <= mem\[i_rd_addr\[port_index\]\];\n'
                      r'                end\n            end', storage)
    if match is None:
        raise ValueError('Synchronous storage read behavior requires verification')
    return match.group(0).replace('i_rd_en', 'tags_i_rd_en').replace('i_rd_addr', 'tags_i_rd_addr').replace(
        'o_rd_data', 'tags_o_rd_data').replace('mem[', 'memory_state[')


def helper(source, storage, name):
    ports = int(re.search(r'\.p_read_ports\((\d+)\)', tag_instance(source)).group(1))
    body = read_assignments(source).replace('[metadata_way]', '')
    return f'''module {name} #(parameter int SETS=128, LB=4, SI=$clog2(SETS)) (
    input logic clk, offer_capture, offer_fresh_q,
    input logic [31:LB] memory_state[SETS],
    input logic [SI-1:0] lookup_read_set, pf_set, initial_pf_set, next_pf_set,
    input logic [SI-1:0] offer_set_q, offer_next_set_q, hint_set,
    output logic [5*(32-LB)-1:0] observations
);
localparam int p_tag_width=32-LB;
logic [31:LB] lookup_tag, pf_tag, incoming_tag, next_tag, hint_lookup_tag;
{read_declarations(source)}
{body}
for (genvar port_index=0; port_index<{ports}; port_index++) begin : g_read
{storage_read_body(storage)}
end
assign observations = {{lookup_tag,pf_tag,incoming_tag,next_tag,hint_lookup_tag}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='f178178b839e5e4019e42fd52bdfece6526ebe96')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT, text=True)
    storage = (ROOT / STORAGE).read_text()
    if normalize_source(current, reference) != reference:
        raise ValueError('Additional cache changes require verification')
    if fresh_state(current) != fresh_state(reference):
        raise ValueError('Offer qualification timing changed')
    for source in (reference, current):
        audit_consumers(source)
    # 写入连接及 regfile 的写入行为相同，任意公共存储内容可作为同步读取的输入。
    old_instance = tag_instance(reference).replace('.p_read_ports(7)', '.p_read_ports(5)')
    if old_instance != tag_instance(current):
        raise ValueError('Storage write or read timing connections changed')
    rtl = out / 'tag_ports.sv'
    rtl.write_text(helper(reference, storage, 'reference_tags') + helper(current, storage, 'current_tags') + f'''
module tag_port_proof #(parameter int SETS=128, LB=4, SI=$clog2(SETS)) (
    input logic clk, rst_n, configuration_accept, offer_capture,
    input logic [31:LB] memory_state[SETS],
    input logic [SI-1:0] lookup_read_set, pf_set, initial_pf_set, next_pf_set,
    input logic [SI-1:0] offer_set_q, offer_next_set_q, hint_set,
    output logic equivalent
);
logic configured, offer_fresh_q;
logic [5*(32-LB)-1:0] reference_observations, current_observations;
{fresh_state(current)}
always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) configured <= 1'b0;
    else if (configuration_accept) configured <= 1'b1;
end
reference_tags #(.SETS(SETS),.LB(LB)) u_reference (.observations(reference_observations), .*);
current_tags #(.SETS(SETS),.LB(LB)) u_current (.observations(current_observations), .*);
assign equivalent = !configured || reference_observations == current_observations;
endmodule
''')
    cases = []
    for sets, lb in ((2, 3), (8, 4), (32, 4), (128, 4), (128, 8)):
        name = f'sets{sets}_line{1 << lb}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text(f'read_slang --top tag_port_proof -GSETS={sets} -GLB={lb} ' +
                          shlex.quote(str(rtl)) + '\n' +
                          'prep -top tag_port_proof -flatten\nasync2sync\nopt\n' +
                          'sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 '
                          '-prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise RuntimeError('Tag-port induction incomplete: ' + name)
        cases.append({'SETS': sets, 'LINE_BYTES': 1 << lb, 'observed_bits': 5*(32-lb), 'passed': True,
                      'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    sha = lambda value: hashlib.sha256(value).hexdigest()
    result = {'passed': True, 'reference_ref': args.reference_ref,
              'source_sha256': sha(current.encode()), 'reference_sha256': sha(reference.encode()),
              'storage_sha256': sha(storage.encode()), 'proof_source_sha256': sha(rtl.read_bytes()),
              'remaining_module_body_identical': True, 'write_connections_identical': True,
              'initial_reset': True, 'memory_contents_constrained': False, 'addresses_constrained': False,
              'events_constrained_after_reset': False,
              'observation_qualification': 'configured; every tag consumer requires a valid entry qualified by configured',
              'method': 'Source-derived synchronous regfile read and offer selector; temporal induction for every tag output.',
              'cases': cases}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('TAG_PORT_EQUIVALENCE_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
