#!/usr/bin/env python3
"""比较活动预取组号和快照匹配状态的实际时钟更新过程。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')


def source_path(root: Path) -> Path:
    child = root / SOURCE.with_name('conv_windowed_cache.sv')
    return child if child.is_file() else root / SOURCE


FIELDS = ('windowed_q', 'pf_addr', 'pf_index', 'pf_index_valid',
          'pf_snapshot_set', 'pf_snapshot_valid')
PORTS = '''input logic clk,rst_n,cfg_valid,cfg_ready,cfg_windowed,
input logic pf_active_valid,clearing,metadata_enable,metadata_fill_good,
input logic [3:0] pf_count,
input logic [SI-1:0] fill_set,
input logic [63:0] pf_selected_keys,
input logic [64:0] prefetch_payload_o_rd_data'''


def model(root: Path, name: str) -> str:
    spec = importlib.util.spec_from_file_location('cache_data_statements',
                                                ROOT / 'test/cache_bram_reset/check_four_state.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.FIELDS = dict.fromkeys(FIELDS)
    text = source_path(root).read_text()
    first = text.index('module conv_windowed_cache')
    text = text[first:text.index('\nendmodule', first)]
    blocks, captured = [], set()
    for match in re.finditer(r'always_ff\s*@\s*\(([^)]*)\)\s*begin', text):
        start, depth = match.end() - len('begin'), 0
        for boundary in re.finditer(r'\bbegin\b|\bend\b', text[start:]):
            depth += 1 if boundary[0] == 'begin' else -1
            if depth == 0:
                selected = text[start:start + boundary.end()]
                break
        else:
            raise RuntimeError('预取时钟过程未完整提取')
        if not re.search(r'\b(' + '|'.join(FIELDS) + r')\s*<=', selected):
            continue
        body = helper.Statements(selected).statement()
        blocks.append('always_ff @(' + match[1] + ') ' + body)
        captured.update(re.findall(r'\b(' + '|'.join(FIELDS) + r')\s*<=', body))
    if captured != set(FIELDS):
        raise RuntimeError('预取字段未完整提取')
    first = text.index('  function automatic logic [SI-1:0] cache_set')
    last = text.index('  endfunction', first) + len('  endfunction')
    function = text[first:last]
    expression = re.search(r'  assign pf_set = [^;]+;', text)[0]
    ready = re.search(r'  wire pf_lookup_ready = [^;]+;', text)[0]
    ready = ready.replace('wire pf_lookup_ready =', 'assign pf_lookup_ready =')
    saved_match = ''
    if '  logic pf_lookup_set_match,' in text:
        first = text.index('  // 活动预取与读取快照使用同一边沿的组号')
        last = text.index('  wire [SI-1:0] initial_pf_set', first)
        saved_match = '''logic pf_lookup_set_match,pf_lookup_set_match_q,pf_lookup_set_match_valid;
logic [SI-1:0] pf_snapshot_set_next,pf_lookup_set_next;
''' + text[first:last]
    return f'''module {name} #(parameter int SI=4,LB=7)({PORTS},output logic pf_lookup_ready);
logic windowed_q,pf_index_valid,pf_snapshot_valid;
logic [31:0] pf_addr,pf_index;
logic [SI-1:0] pf_set,pf_snapshot_set;
{function}
{expression}
{saved_match}
{ready}
{chr(10).join(blocks)}
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    models = out / 'prefetch_state.sv'
    models.write_text(''.join(model(root, name) for name, root in roots.items()))
    profiles = []
    for si, lb in ((1, 4), (3, 4), (4, 7), (7, 4), (8, 8)):
        commands = []
        for label in roots:
            commands += [
                f'read_slang --top {label} -GSI={si} -GLB={lb} ' + shlex.quote(str(models)),
                f'prep -top {label} -flatten', 'async2sync', 'opt_clean',
                f'design -stash {label}',
            ]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current comparison', 'hierarchy -top comparison',
                     'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out / f'{si}_{lb}.ys', out / f'{si}_{lb}.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                        '--worker', str(script)], stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=60)
        if completed.returncode or 'Equivalence successfully proven' not in log.read_text():
            raise RuntimeError('预取快照状态证明未完成: ' + str(log))
        profiles.append({'set_index_width': si, 'line_offset_width': lb, 'passed': True})
    names = re.sub(r'input logic(?: \[[^\]]+\])? ', '', PORTS).replace('\n', '').replace(' ', '').split(',')
    connections = ','.join(f'.{name}({name})' for name in names)
    bench = out / 'four_state.sv'
    bench.write_text(f'''module tb;
localparam integer SI=4,LB=7;
logic clk=0,rst_n=0,cfg_valid,cfg_ready,cfg_windowed,pf_active_valid,clearing;
logic metadata_enable,metadata_fill_good;
logic [3:0] pf_count;
logic [SI-1:0] fill_set;
logic [63:0] pf_selected_keys;
logic [64:0] prefetch_payload_o_rd_data;
wire expected,actual;
reference #(.SI(SI),.LB(LB)) u_reference({connections},.pf_lookup_ready(expected));
current #(.SI(SI),.LB(LB)) u_current({connections},.pf_lookup_ready(actual));
logic [31:0] rng=32'h523aca41,controls,keys_low,keys_high,payload_low,payload_high;
integer checks=0;
task random_word(output logic [31:0] value,input integer mode);
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);value=rng;
  if(mode) for(integer bit_index=0;bit_index<32;bit_index++) begin
    if ((bit_index+integer'(rng[4:0]))%13==0) value[bit_index]=1'bx;
    if ((bit_index+integer'(rng[9:5]))%17==0) value[bit_index]=1'bz;
  end
endtask
task compare;
  #1;
  if(expected!==actual)$fatal(1,"prefetch snapshot differs check=%0d expected=%b actual=%b",checks,expected,actual);
  checks++;
endtask
initial begin
  for(integer sample=0;sample<100000;sample++) begin
    clk=0;
    random_word(controls,sample%3);random_word(keys_low,sample%3);
    random_word(keys_high,sample%3);random_word(payload_low,sample%3);
    random_word(payload_high,sample%3);
    {{cfg_valid,cfg_ready,cfg_windowed,pf_active_valid,clearing,metadata_enable,
      metadata_fill_good,pf_count,fill_set}}=controls[14:0];
    pf_selected_keys={{keys_high,keys_low}};
    prefetch_payload_o_rd_data={{controls[15],payload_high,payload_low}};
    rst_n=sample%113>2;
    if(sample%331==4)rst_n=1'bx;
    if(sample%337==8)rst_n=1'bz;
    compare();clk=1;compare();clk=0;compare();
  end
  $display("CACHE_PREFETCH_SNAPSHOT_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    compiler = shutil.which('iverilog') or '/home/agent/.local/bin/iverilog'
    runner = shutil.which('vvp') or '/home/agent/.local/bin/vvp'
    binary = out / 'four_state.vvp'
    completed = subprocess.run([compiler, '-g2012', '-s', 'tb', '-o', str(binary),
                                str(models), str(bench)], capture_output=True, text=True)
    (out / 'compile.log').write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    completed = subprocess.run([runner, str(binary)], capture_output=True, text=True, timeout=120)
    (out / 'four_state.log').write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    match = re.search(r'CACHE_PREFETCH_SNAPSHOT_FOUR_STATE_PASS checks=(\d+)', completed.stdout)
    if not match:
        raise RuntimeError('预取快照四态比较未完成')
    result = {'passed': True, 'external_inputs_constrained': False,
              'compared': 'actual prefetch payload, configuration and snapshot clock updates',
              'profiles': profiles, 'four_state_comparisons': int(match[1]),
              'source_sha256': {label: hashlib.sha256(source_path(root).read_bytes()).hexdigest()
                                for label, root in roots.items()},
              'model_sha256': hashlib.sha256(models.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
