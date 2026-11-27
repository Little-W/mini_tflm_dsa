"""按端口声明计算四态输入宽度，并生成逐位状态覆盖检查。"""
from __future__ import annotations

import re


def packed_width(declaration):
    """保留参数表达式，将降序位范围转换为独立的常量宽度表达式。"""
    declaration = (declaration or '').strip()
    if not declaration:
        return '1'
    if not re.fullmatch(r'\[[^\]]+\]', declaration):
        raise ValueError('端口位范围无法解析：' + declaration)
    high, low = declaration[1:-1].rsplit(':', 1)
    return f'(1 + ({high}) - ({low}))'


def coverage_declarations(width_name):
    return f'''logic [3:0] input_seen [0:{width_name}-1];
integer input_state_samples [0:3];
integer input_bits_covered=0;
'''


def coverage_tasks(width_name, concatenation):
    """使用运行期实际位宽复核声明，逐位记录 0、1、X、Z 四种状态。"""
    return f'''task automatic initialize_input_coverage;
begin
 if ({width_name} <= 0 || {width_name} != $bits({concatenation}))
  $fatal(1,"Input declaration width differs from elaborated ports");
 for(integer index=0;index<{width_name};index++)input_seen[index]='0;
 for(integer state_index=0;state_index<4;state_index++)input_state_samples[state_index]=0;
end
endtask
task automatic observe_inputs;
 logic [{width_name}-1:0] observed;
 integer state_index;
begin
 observed={concatenation};
 for(integer index=0;index<{width_name};index++)begin
  case(observed[index])
   1'b0:state_index=0;1'b1:state_index=1;1'bx:state_index=2;1'bz:state_index=3;
  endcase
  input_seen[index][state_index]=1'b1;
  input_state_samples[state_index]++;
 end
end
endtask
task automatic check_input_coverage;
begin
 input_bits_covered=0;
 for(integer index=0;index<{width_name};index++)begin
  if(input_seen[index]!==4'b1111)$fatal(1,"Input bit lacks four-state coverage bit=%0d seen=%b",index,input_seen[index]);
  input_bits_covered++;
 end
 $display("INPUT_COVERAGE bits=%0d covered=%0d zero=%0d one=%0d unknown=%0d high_impedance=%0d",
  {width_name},input_bits_covered,input_state_samples[0],input_state_samples[1],
  input_state_samples[2],input_state_samples[3]);
end
endtask
'''


def parse_coverage(output):
    match = re.search(r'INPUT_COVERAGE bits=(\d+) covered=(\d+) zero=(\d+) one=(\d+) '
                      r'unknown=(\d+) high_impedance=(\d+)', output)
    if not match:
        raise RuntimeError('四态输入覆盖统计缺失')
    values = list(map(int, match.groups()))
    if values[0] <= 0 or values[0] != values[1] or min(values[2:]) <= 0:
        raise RuntimeError('四态输入覆盖不完整')
    return dict(input_bits=values[0], all_four_states_per_bit=True, covered_bits=values[1],
                bit_observations=dict(zip(('zero','one','unknown','high_impedance'),values[2:])))
