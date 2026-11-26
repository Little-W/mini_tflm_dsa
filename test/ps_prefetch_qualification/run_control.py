#!/usr/bin/env python3
"""直接提取帧准备和预取资格，检查全部二态输入及四态控制组合。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/ps_compact/ps_frame_store.sv'
FIELDS = [('frame_request', 1), ('frame_accept', 1), ('command_accepted', 1),
          ('command_present', 1), ('configuration_ready', 1), ('request_pending_q', 1),
          ('request_fits_q', 1), ('complete_eligible', 1), ('frame_init_q', 1),
          ('read_remaining_q', 1), ('prefetch_credit_available', 1), ('clear_metadata', 1),
          ('encoder_done', 1), ('commit_next_complete_q', 1), ('frame_single_row_q', 1),
          ('request_q.init', 1), ('request_q.legal', 1), ('request_q.id', 4), ('frame_id_q', 4)]
WIDTH = sum(width for _, width in FIELDS)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text, name):
    marker = '    assign prepare_state_eligible' if '    assign prepare_state_eligible' in text else '    assign prepare_eligible'
    start = text.index(marker)
    prepare = text[start:text.index('    always_comb begin', start)]
    start = text.index('    logic prefetch_prepare, prefetch_fire;')
    prefetch = text[start:text.index('    always_comb begin\n        case (capacity_fault)', start)]
    start = text.index('    wire cancel_prepared')
    cancel = text[start:text.index(';', start) + 1]
    declarations, assignments, offset = [], [], 0
    for field, width in FIELDS:
        if '.' not in field:
            declarations.append(f'wire [{width-1}:0] {field};')
        assignments.append(f'assign {field}=values[{offset}+:{width}];')
        offset += width
    return f'''// 模块作用：以自由输入表示实际状态，检查帧准备和读取资格的组合语义。
module {name}(
 input wire [{WIDTH-1}:0] values, // 请求、接受、存储状态及帧编号。
 output wire [2:0] result // 帧准备、首行读取及所有预取资格。
);
typedef struct packed {{logic [3:0] id; logic init, legal;}} request_context_t;
request_context_t request_q;
logic prepare_eligible, prepare_state_eligible;
''' + '\n'.join(declarations + assignments) + '\n' + cancel + '\n' + prepare + prefetch + '''
assign result={prepare_eligible,prepare_read_eligible,prefetch_eligible};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8847f9ac')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    model = out / 'qualification.sv'
    model.write_text(extract(reference, 'reference_qualification') + extract(current, 'current_qualification') + f'''
// 模块作用：比较两版实际控制表达式的全部输出。
module qualification_compare(
 input wire [{WIDTH-1}:0] values, // 全部控制和状态输入。
 output wire equivalent // 三个资格结果均逐位相同。
);
wire [2:0] expected, actual;
reference_qualification u_reference(values,expected);
current_qualification u_current(values,actual);
assign equivalent=expected==actual;
endmodule
''')
    script = out / 'formal.ys'
    script.write_text('read_slang --top qualification_compare ' + shlex.quote(str(model)) + '\n' +
                     'prep -top qualification_compare -flatten\nsat -verify -prove equivalent 1\n')
    with (out / 'formal.log').open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    assert 'SUCCESS!' in (out / 'formal.log').read_text()
    bench = out / 'four_state.sv'
    bench.write_text(f'''// 模块作用：遍历四个关键控制信号的四态组合，并检查实际资格表达式。
module tb;
reg [{WIDTH-1}:0] values;
wire [2:0] expected,actual;
integer sample,bit_index,choice;
reg [31:0] state=32'h6fa90385;
reference_qualification u_reference(values,expected);
current_qualification u_current(values,actual);
initial begin
 for(sample=0;sample<32768;sample=sample+1)begin
  for(bit_index=0;bit_index<{WIDTH};bit_index=bit_index+1)begin
   state=state^(state<<13);state=state^(state>>17);state=state^(state<<5);
   choice=bit_index<4 ? ((sample>>(2*bit_index))&3) : sample<8192 ? int'(state[0]) : int'(state[1:0]);
   case(choice)
    0:values[bit_index]=1'b0;
    1:values[bit_index]=1'b1;
    2:values[bit_index]=1'bx;
    3:values[bit_index]=1'bz;
   endcase
  end
  #1;
  if(actual!==expected)$fatal(1,"Prefetch qualification differs at sample %0d",sample);
 end
 $display("PS_PREFETCH_FOUR_STATE_PASS samples=32768");$finish;
end
endmodule
''')
    binary = out / 'four_state.vvp'
    with (out / 'build.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(model), str(bench)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out / 'four_state.log').open('w') as stream:
        subprocess.run(['vvp', str(binary)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    assert 'PS_PREFETCH_FOUR_STATE_PASS' in (out / 'four_state.log').read_text()
    assert current == (ROOT / SOURCE).read_text()
    report = dict(passed=True, reference=args.reference, source_sha256=digest(ROOT / SOURCE),
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  model_sha256=digest(model), test_sha256=digest(Path(__file__)),
                  inputs_constrained=False, output_bits=3, four_state_comparisons=32768,
                  formal_log_sha256=digest(out / 'formal.log'),
                  four_state_log_sha256=digest(out / 'four_state.log'))
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PS_PREFETCH_CONTROL_PASS', flush=True)


if __name__ == '__main__':
    main()
