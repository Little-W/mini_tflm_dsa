#!/usr/bin/env python3
"""验证窗口循环有效位选择和完整有符号区间比较。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        result = subprocess.run(list(map(str, command)), stdout=stream,
                                stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--tool-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = Path('rtl/npu/conv/vector_engine.sv')
    current = read_current_source(args.source_root / path)
    reference = read_current_source(args.reference_root / path)
    source_digest = hashlib.sha256(current.encode()).hexdigest()
    reference_digest = hashlib.sha256(reference.encode()).hexdigest()
    # 局部模型使用自己的形参名，实际宽度表达式和条件保持不变。
    for old, new in (('p_window_lanes', 'WINDOW_LANES'), ('p_window_bank_w', 'WINDOW_BANK_W')):
        current = re.sub(r'\b' + old + r'\b', new, current)
        reference = re.sub(r'\b' + old + r'\b', new, reference)
    marker = '  for (genvar bank=0;bank<WINDOW_LANES;bank++) begin : g_window_bank'
    finish = '    if (p_input_bank_storage) begin : g_registered_write'
    selected_bank = current.split(marker, 1)[1].split(finish, 1)[0]
    reference_bank = reference.split(marker, 1)[1].split(finish, 1)[0]
    selected_pending = current.split('  if ((WINDOW_LANES & (WINDOW_LANES-1)) == 0)', 1)[1]
    selected_pending = '  if ((WINDOW_LANES & (WINDOW_LANES-1)) == 0)' + selected_pending.split(
        '  // 保存本拍写入是否非空', 1)[0]
    header = '''module NAME #(parameter integer WINDOW_LANES=8,
  parameter integer WINDOW_BANK_W=$clog2(WINDOW_LANES))(
  input wire [WINDOW_LANES-1:0] window_lane_valid,
  input wire [WINDOW_BANK_W-1:0] window_first_bank,
  output wire [WINDOW_LANES-1:0] window_bank_valid_next,
  output wire window_write_pending_next
);
  wire window_write_valid[WINDOW_LANES];
  for(genvar i=0;i<WINDOW_LANES;i++)assign window_write_valid[i]=window_lane_valid[i];
  for(genvar bank=0;bank<WINDOW_LANES;bank++)begin:g_window_bank
'''
    model_text = header.replace('NAME', 'rotation_reference') + reference_bank + '''  end
  assign window_write_pending_next=|window_bank_valid_next;
endmodule
''' + header.replace('NAME', 'rotation_selected') + selected_bank + '  end\n' + selected_pending + '\nendmodule\n'
    model_text += '''module rotation_property #(parameter integer LANES=8)(
  input wire [LANES-1:0] valid,
  input wire [$clog2(LANES)-1:0] first,
  output wire formal_equal
);
 wire [LANES-1:0] old_valid,new_valid;
 wire old_pending,new_pending;
 rotation_reference #(.WINDOW_LANES(LANES)) reference(valid,first,old_valid,old_pending);
 rotation_selected #(.WINDOW_LANES(LANES)) selected(valid,first,new_valid,new_pending);
 assign formal_equal=({old_valid,old_pending} === {new_valid,new_pending});
endmodule
'''
    bound = (args.source_root / 'rtl/npu/conv/vector_interval_bound.sv').read_text()
    model_text += bound + '''
module interval_property(
 input wire signed [16:0] coordinate,minimum,maximum,
 output wire formal_equal
);
 wire selected;
 vector_interval_bound u_bound(coordinate,minimum,maximum,selected);
 assign formal_equal=(selected === ((coordinate>=minimum)&&(coordinate<maximum)));
endmodule
'''
    model = out / 'model.sv'
    model.write_text(model_text)
    profiles = []
    sizes = (2, 3, 4, 5, 7, 8, 12, 16, 32)
    for name, top, option in [(f'rotation{n}', 'rotation_property', f'-GLANES={n}') for n in sizes] + [
            ('interval', 'interval_property', '')]:
        script = out / (name + '.ys')
        script.write_text(f'read_slang --top {top} {option} {model}\n'
                          f'prep -top {top} -flatten\n'
                          'sat -enable_undef -set-def-inputs -verify -prove formal_equal 1 -show-inputs -show-outputs\n')
        log = out / (name + '.log')
        run([sys.executable, args.tool_root / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        profiles.append(dict(name=name, passed=True, input_constraints='all binary inputs; unused indices included', log_sha256=sha(log)))
    bench = out / 'four_state.sv'
    text = '''module tb;
 logic [31:0] valid;
 logic [4:0] first;
 logic signed [16:0] coordinate,minimum,maximum;
 wire [8:0] rotation_equal;
 wire interval_equal;
 integer i,j,checks=0;
 integer unsigned random_state=32'h6b70bd11;
 function automatic integer unsigned random_next;
  random_state=random_state^(random_state<<13);
  random_state=random_state^(random_state>>17);
  random_state=random_state^(random_state<<5);
  return random_state;
 endfunction
 function automatic logic four(input logic [1:0] value);
  case(value)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
'''
    for index, n in enumerate(sizes):
        width = (n-1).bit_length()
        text += f'rotation_property #(.LANES({n})) r{n}(valid[{n-1}:0],first[{width-1}:0],rotation_equal[{index}]);\n'
    text += '''interval_property interval(coordinate,minimum,maximum,interval_equal);
 initial begin
  for(i=0;i<40000;i++)begin
   valid=random_next();first=5'(random_next());
   coordinate=17'(random_next());minimum=17'(random_next());maximum=17'(random_next());
   if(i%5==0)valid='0;
   if(i%5==1)valid='1;
   if(i%3==0)for(j=0;j<32;j++)valid[j]=four(2'(random_next()));
   if(i%3!=1)for(j=0;j<5;j++)first[j]=four(2'(random_next()));
   if(i%7==0)coordinate[5'(random_next())%17]=four(2'(random_next()));
   if(i%7==1)minimum[5'(random_next())%17]=four(2'(random_next()));
   if(i%7==2)maximum[5'(random_next())%17]=four(2'(random_next()));
   if(i%11==0)coordinate=minimum;
   if(i%11==1)coordinate=maximum;
   #1;
   if(rotation_equal!==9'h1ff)$fatal(1,"窗口循环选择结果不一致");
   if(interval_equal!==1'b1)$fatal(1,"有符号区间结果不一致");
   checks+=10;
  end
  $display("WINDOW_INTERVAL_PASS comparisons=%0d",checks);$finish;
 end
endmodule
'''
    bench.write_text(text)
    executable = out / 'four_state.vvp'
    run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb', '-o', executable, model, bench], out/'compile.log')
    run(['/home/agent/.local/bin/vvp', executable], out/'four_state.log')
    report = dict(passed=True, source_sha256=source_digest, reference_sha256=reference_digest,
                  formal=profiles, four_state_comparisons=400000, model_sha256=sha(model),
                  test_sha256=sha(Path(__file__)), simulation_log_sha256=sha(out/'four_state.log'))
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    main()
