"""展开四态测试的实际信号宽度，并检查每一位的 0、1、X、Z 覆盖。"""
from pathlib import Path
import re
import subprocess


def expanded_widths(out, constants, declarations, names, type_sources=()):
    """使用测试端口的原始声明取得每个字段的实际展开宽度。"""
    out = Path(out)
    source = out / 'input_widths.sv'
    binary = out / 'input_widths.vvp'
    log = out / 'input_widths.log'
    source.write_text('module input_widths;\n' + constants + '\n' + declarations +
                      '\ninitial begin\n' + '\n'.join(
                          f'$display("INPUT_WIDTH {name} %0d", $bits({name}));'
                          for name in names) + '\nend\nendmodule\n')
    with log.open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'input_widths', '-o', str(binary),
                        *map(str, type_sources), str(source)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=60)
        subprocess.run(['vvp', str(binary)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=60)
    widths = {name: int(width) for name, width in re.findall(
        r'^INPUT_WIDTH (\w+) (\d+)$', log.read_text(), re.M)}
    if set(widths) != set(names) or any(width <= 0 for width in widths.values()):
        raise RuntimeError('四态测试输入字段的展开宽度不完整')
    return widths


def declarations(width):
    return f'''
integer coverage_zero[0:{width}-1], coverage_one[0:{width}-1];
integer coverage_x[0:{width}-1], coverage_z[0:{width}-1];
integer total_zero=0, total_one=0, total_x=0, total_z=0;
'''


def initialize(width, names):
    return f'''
  if ({width} <= 0 || $bits(stimulus) != {width} || $bits({{{names}}}) != {width})
    $fatal(1,"four-state input width differs from expanded ports");
  for(integer bit_index=0;bit_index<{width};bit_index++)begin
    coverage_zero[bit_index]=0;coverage_one[bit_index]=0;
    coverage_x[bit_index]=0;coverage_z[bit_index]=0;
  end
'''


def sample(width):
    return f'''
    for(integer coverage_index=0;coverage_index<{width};coverage_index++)begin
      case(stimulus[coverage_index])
        1'b0:begin coverage_zero[coverage_index]++;total_zero++;end
        1'b1:begin coverage_one[coverage_index]++;total_one++;end
        1'bx:begin coverage_x[coverage_index]++;total_x++;end
        1'bz:begin coverage_z[coverage_index]++;total_z++;end
      endcase
    end
'''


def finish(width):
    return f'''
  for(integer bit_index=0;bit_index<{width};bit_index++)begin
    if(coverage_zero[bit_index]==0 || coverage_one[bit_index]==0 ||
       coverage_x[bit_index]==0 || coverage_z[bit_index]==0)
      $fatal(1,"four-state input bit has incomplete coverage bit=%0d",bit_index);
  end
  $display("FOUR_STATE_COVERAGE width=%0d zero=%0d one=%0d x=%0d z=%0d covered_bits=%0d",
      {width},total_zero,total_one,total_x,total_z,{width});
'''


def result(log, widths):
    text = Path(log).read_text()
    match = re.search(r'FOUR_STATE_COVERAGE width=(\d+) zero=(\d+) one=(\d+) '
                      r'x=(\d+) z=(\d+) covered_bits=(\d+)', text)
    if not match:
        raise RuntimeError('四态逐位覆盖报告未生成')
    width, zero, one, unknown, high_impedance, covered = map(int, match.groups())
    if width != sum(widths.values()) or covered != width:
        raise RuntimeError('四态逐位覆盖数量与实际端口宽度不一致')
    return {'input_bits': width, 'port_widths': widths, 'fully_covered_bits': covered,
            'bit_values': {'0': zero, '1': one, 'X': unknown, 'Z': high_impedance}}
