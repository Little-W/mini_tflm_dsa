#!/usr/bin/env python3
"""从实际保存语句比较缓存载荷在复位、配置和四态控制下的更新行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')


def source_path(root: Path) -> Path:
    child = root / SOURCE.with_name('conv_windowed_cache.sv')
    return child if child.is_file() else root / SOURCE


FIELDS = {
    'lookup_snapshot_set': 'SI', 'pf_snapshot_set': 'SI',
    'incoming_snapshot_set': 'SI', 'next_snapshot_set': 'SI',
    'incoming_hold_snapshot_set': 'SI', 'next_hold_snapshot_set': 'SI',
    'hint_snapshot_set': 'SI', 'pf_pick': '3', 'pf_addr': '32',
    'pf_index': '32', 'pf_epoch': '32', 'pf_retire': '32',
    'pf_index_valid': '1', 'hint_value_q': '32',
}
PORTS = '''input logic clk,rst_n,cfg_valid,cfg_ready,
    input logic hint_pending_q,hint_valid,hint_lookup_ready,hint_buffered,
    input logic pf_active_valid,clearing,
    input logic [3:0] pf_count,
    input logic [2:0] pf_pick_comb,
    input logic [SI-1:0] lookup_read_set,pf_set,initial_pf_set,next_pf_set,
    input logic [SI-1:0] offer_set_q,offer_next_set_q,hint_set,
    input logic [63:0] pf_selected_keys,
    input logic [64:0] prefetch_payload_o_rd_data,
    input logic [31:0] hint_next'''


class Statements:
    """保留字段赋值及其全部控制条件，移除与所选字段无关的语句。"""

    def __init__(self, text: str) -> None:
        clean = re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)
        self.tokens = re.findall(r'[a-zA-Z_$][\w$]*|\d+\x27[\w?]+|\d+|<=|>=|===|!==|==|!=|&&|\|\||<<|>>|\S', clean)
        self.index = 0

    def balanced(self, first: str, last: str) -> list[str]:
        assert self.tokens[self.index] == first
        self.index += 1
        start, depth = self.index, 1
        while depth:
            token = self.tokens[self.index]
            self.index += 1
            depth += (token == first) - (token == last)
        return self.tokens[start:self.index - 1]

    def statement(self) -> str:
        token = self.tokens[self.index]
        if token == 'begin':
            self.index += 1
            parts = []
            while self.tokens[self.index] != 'end':
                part = self.statement()
                if part:
                    parts.append(part)
            self.index += 1
            return 'begin\n' + '\n'.join(parts) + '\nend' if parts else ''
        if token == 'if':
            self.index += 1
            condition = ' '.join(self.balanced('(', ')'))
            selected = self.statement()
            other = ''
            if self.index < len(self.tokens) and self.tokens[self.index] == 'else':
                self.index += 1
                other = self.statement()
            if not selected and not other:
                return ''
            return ('if (' + condition + ') ' + (selected or 'begin end') +
                    (' else ' + other if other else ''))
        if token == 'case':
            self.index += 1
            condition = ' '.join(self.balanced('(', ')'))
            choices = []
            while self.tokens[self.index] != 'endcase':
                label = []
                while self.tokens[self.index] != ':':
                    label.append(self.tokens[self.index])
                    self.index += 1
                self.index += 1
                selected = self.statement()
                if selected:
                    choices.append(' '.join(label) + ': ' + selected)
            self.index += 1
            return 'case (' + condition + ')\n' + '\n'.join(choices) + '\nendcase' if choices else ''
        start = self.index
        while self.tokens[self.index] != ';':
            self.index += 1
        self.index += 1
        values = self.tokens[start:self.index]
        return ' '.join(values) if values and values[0] in FIELDS else ''


def extract(root: Path, name: str) -> str:
    text = source_path(root).read_text()
    first = text.index('module conv_windowed_cache')
    text = text[first:text.index('\nendmodule', first)]
    blocks = []
    captured = []
    for match in re.finditer(r'always_ff\s*@\s*\(([^)]*)\)\s*begin', text):
        start = match.end() - len('begin')
        depth = 0
        stop = None
        for boundary in re.finditer(r'\bbegin\b|\bend\b', text[start:]):
            depth += 1 if boundary[0] == 'begin' else -1
            if depth == 0:
                stop = start + boundary.end()
                break
        if stop is None:
            raise RuntimeError('时钟过程的范围未确定')
        selected = text[start:stop]
        if not re.search(r'\b(' + '|'.join(FIELDS) + r')\s*<=', selected):
            continue
        parser = Statements(selected)
        body = parser.statement()
        if not body:
            continue
        blocks.append('always_ff @(' + match[1] + ') ' + body)
        captured += re.findall(r'\b(' + '|'.join(FIELDS) + r')\s*<=', body)
    if sorted(captured) != sorted(FIELDS):
        raise RuntimeError('保存字段未完整提取: ' + str(captured))
    ports = ',\n'.join(f'output logic [{width}-1:0] {field}' for field, width in FIELDS.items())
    return f'module {name} #(parameter int SI=4) ({PORTS},\n{ports});\n' + '\n'.join(blocks) + '\nendmodule\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    models = out / 'data_updates.sv'
    models.write_text(''.join(extract(root, name) for name, root in roots.items()))
    names = re.sub(r'input logic(?: \[[^\]]+\])? ', '', PORTS).replace('\n', '').replace(' ', '').split(',')
    # 端口声明按每行的共同位宽展开，测试输入以单独声明保持清晰。
    declarations = '''logic clk=0,rst_n=0,cfg_valid,cfg_ready;
logic hint_pending_q,hint_valid,hint_lookup_ready,hint_buffered,pf_active_valid,clearing;
logic [3:0] pf_count;
logic [2:0] pf_pick_comb;
logic [SI-1:0] lookup_read_set,pf_set,initial_pf_set,next_pf_set,offer_set_q,offer_next_set_q,hint_set;
logic [63:0] pf_selected_keys;
logic [64:0] prefetch_payload_o_rd_data;
logic [31:0] hint_next;'''
    instances = []
    for label in roots:
        for field, width in FIELDS.items():
            declarations += f'\nwire [{width}-1:0] {label}_{field};'
        connections = [f'.{name}({name})' for name in names]
        connections += [f'.{field}({label}_{field})' for field in FIELDS]
        instances.append(f'{label} #(.SI(SI)) u_{label}(' + ','.join(connections) + ');')
    expected = ','.join('reference_' + name for name in FIELDS)
    actual = ','.join('current_' + name for name in FIELDS)
    bench = out / 'four_state.sv'
    bench.write_text(f'''module tb;
localparam integer SI=4;
{declarations}
{chr(10).join(instances)}
integer checks=0;
logic [31:0] rng=32'h7b613ac4;
task random_word(output logic [31:0] value);
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);value=rng;
  for(integer bit_index=0;bit_index<32;bit_index++) begin
    if ((bit_index+integer'(rng[4:0]))%13==0) value[bit_index]=1'bx;
    if ((bit_index+integer'(rng[9:5]))%17==0) value[bit_index]=1'bz;
  end
endtask
task compare;
  #1;
  if ({{{expected}}} !== {{{actual}}}) $fatal(1,"cache data update mismatch check=%0d",checks);
  checks++;
endtask
logic [31:0] controls,sets,keys_low,keys_high,payload_low,payload_high;
initial begin
  for(integer sample=0;sample<100000;sample++) begin
    clk=0;
    random_word(controls);random_word(sets);
    random_word(keys_low);random_word(keys_high);
    random_word(payload_low);random_word(payload_high);random_word(hint_next);
    {{cfg_valid,cfg_ready,hint_pending_q,hint_valid,hint_lookup_ready,hint_buffered,
      pf_active_valid,clearing,pf_count,pf_pick_comb}}=controls[14:0];
    {{lookup_read_set,pf_set,initial_pf_set,next_pf_set,offer_set_q,offer_next_set_q,hint_set}}=sets[27:0];
    pf_selected_keys={{keys_high,keys_low}};
    prefetch_payload_o_rd_data={{controls[15],payload_high,payload_low}};
    rst_n=sample%113>2;
    compare();clk=1;compare();clk=0;compare();
  end
  $display("CACHE_DATA_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    binary = out / 'four_state.vvp'
    compiler = shutil.which('iverilog') or '/home/agent/.local/bin/iverilog'
    runner = shutil.which('vvp') or '/home/agent/.local/bin/vvp'
    command = [compiler, '-g2012', '-s', 'tb', '-o', str(binary), str(models), str(bench)]
    compile_result = subprocess.run(command, capture_output=True, text=True)
    (out / 'compile.log').write_text(compile_result.stdout + compile_result.stderr)
    compile_result.check_returncode()
    completed = subprocess.run([runner, str(binary)], capture_output=True, text=True, timeout=120)
    (out / 'run.log').write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    match = re.search(r'CACHE_DATA_FOUR_STATE_PASS checks=(\d+)', completed.stdout)
    if not match:
        raise RuntimeError('四态保存比较未完成')
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    result = {'passed': True, 'comparisons': int(match[1]), 'fields': list(FIELDS),
              'reset': 'binary asynchronous reset; unknown control and data inputs',
              'source_sha256': {name: digest(source_path(root)) for name, root in roots.items()},
              'models_sha256': digest(models), 'bench_sha256': digest(bench),
              'log_sha256': digest(out / 'run.log')}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
