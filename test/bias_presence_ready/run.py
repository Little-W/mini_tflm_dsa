#!/usr/bin/env python3
"""穷举偏置需求的四态输入并核对矩阵模块中的完整组合替换。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'rtl/npu/top/npu_bias_presence.sv'
PARENT = ROOT/'rtl/npu/top/npu_matrix_engine.sv'
REFERENCE_EXPRESSION = '''assign exec_bias_present = o_frame_mode_q ?
    (bias_base_nonzero &&
     ((o_is_mode || ws_final_bias) ? frame_exec_final : frame_exec_init) &&
     !bias_zero_o_equal) : controller_bias_base_nonzero;'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(text):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='HEAD')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    reference = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = PARENT.read_text()
    original = subprocess.check_output(['git', 'show', reference+':'+str(PARENT.relative_to(ROOT))], cwd=ROOT, text=True)
    pattern = r'npu_bias_presence\s+u_bias_presence\s*\((.*?)\);'
    instance = re.search(pattern, current, re.S)
    expected = '''.i_frame_mode(o_frame_mode_q),.i_base_nonzero(bias_base_nonzero),
    .i_is_mode(o_is_mode),.i_ws_final_bias(ws_final_bias),
    .i_frame_final(frame_exec_final),.i_frame_init(frame_exec_init),
    .i_address_zero(bias_zero_o_equal),.i_visible_base_nonzero(controller_bias_base_nonzero),
    .o_present(exec_bias_present)'''
    assert instance and tokens(instance[1]) == tokens(expected)
    reference_instance = re.search(pattern, original, re.S)
    if reference_instance:
        assert tokens(reference_instance[1]) == tokens(expected)
        assert tokens(current) == tokens(original)
    else:
        reconstructed = current[:instance.start()]+REFERENCE_EXPRESSION+current[instance.end():]
        assert tokens(reconstructed) == tokens(original)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in [SOURCE, PARENT]}
    model = out/'model.sv'
    model.write_text('''// 偏置需求在完整任意输入下的比较模型。
module proof(
 input wire [7:0] values, // 模式、帧位置与地址条件
 output wire selected, // 当前偏置需求
 output wire reference_value, // 完整条件选择表达式
 output wire equal // 两种表达式相等
);
npu_bias_presence u_dut(
 .i_frame_mode(values[0]),.i_base_nonzero(values[1]),.i_is_mode(values[2]),
 .i_ws_final_bias(values[3]),.i_frame_final(values[4]),.i_frame_init(values[5]),
 .i_address_zero(values[6]),.i_visible_base_nonzero(values[7]),.o_present(selected));
assign reference_value=values[0]?
 (values[1]&&((values[2]||values[3])?values[4]:values[5])&&!values[6]):values[7];
assign equal=selected===reference_value;
endmodule
''')
    tb = out/'tb.sv'
    tb.write_text('''// 枚举全部四态组合，包括模式和地址条件同时未知的情况。
module tb;
reg [7:0] values;wire selected,reference_value,equal;integer checks=0;
proof u_proof(values,selected,reference_value,equal);
initial begin
 for(integer sample=0;sample<65536;sample++)begin
  for(integer bit_index=0;bit_index<8;bit_index++)begin
   case((sample>>(2*bit_index))&3)
    0:values[bit_index]=0;1:values[bit_index]=1;
    2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;
   endcase
  end
  #1;if(equal!==1'b1)$fatal(1,"Bias presence differs values=%b",values);checks++;
 end
 $display("BIAS_PRESENCE_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    records = []
    for mode in ['generic', 'fpga']:
        flags = ['-USYNTHESIS', '-UXILINX_FPGA'] if mode == 'generic' else ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        script, log = out/(mode+'.ys'), out/(mode+'_formal.log')
        script.write_text('read_slang --top proof '+shlex.join(flags+[str(SOURCE), str(model)])+
                          '\nprep -top proof -flatten\nsat -verify -prove equal 1 -show-inputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        assert 'SUCCESS!' in log.read_text()
        binary = out/(mode+'.vvp')
        simulation_flags = flags if mode == 'fpga' else []
        with (out/(mode+'_compile.log')).open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', *simulation_flags, '-o', str(binary),
                            str(SOURCE), str(model), str(tb)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.check_output(['vvp', str(binary)], text=True, timeout=180)
        (out/(mode+'_four_state.log')).write_text(result)
        assert 'PASS checks=65536' in result
        records.append(dict(mode=mode, passed=True, four_state_comparisons=65536,
                            formal_log_sha256=digest(log), four_state_log_sha256=digest(out/(mode+'_four_state.log'))))
    assert hashes == {str(path.relative_to(ROOT)): digest(path) for path in [SOURCE, PARENT]}
    report = dict(passed=True, source_sha256=hashes, input_assumptions=[], profiles=records,
                  four_state_comparisons=131072, test_sha256=digest(Path(__file__)),
                  parent_replacement=dict(reference=reference, ports_verified=True,
                                          complete_remaining_functional_tokens_identical=True))
    (out/'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('BIAS_PRESENCE_PASS', 131072, flush=True)


if __name__ == '__main__':
    main()
