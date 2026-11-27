#!/usr/bin/env python3
"""验证请求上下文与索引寄存器的完整连接、停顿保存和四态传播。"""
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fields = json.loads((HERE / 'request_context_fields.json').read_text())
    inputs = [row for row in fields['ports'] if row[0] == 'input']
    connections = ',\n'.join('.' + row[2] + '(' + row[2] + ')' for row in inputs)
    parameters = [('p_coord_width', '35'), ('p_line_bytes', '128'),
                  ('p_register_descriptor', "1'b1")]
    parameter_connections = ','.join('.' + name + '(' + name + ')' for name, _ in parameters)
    model = out / 'comparison.sv'
    header = '''// 保存完整请求上下文的索引，并比较移位前后寄存的逐周期结果。
module index_register_comparison #(\n'''
    header += ',\n'.join('parameter ' + ('bit' if name == 'p_register_descriptor' else 'int') +
                        ' ' + name + '=' + value for name, value in parameters)
    header += ''') (
  input wire logic i_clk, // 请求寄存器时钟
  input wire logic i_write, // 当前请求字段的写入使能
'''
    header += '\n'.join('  input wire ' + row[1] + ' ' + row[2] + ', // ' + row[4]
                        for row in inputs)
    header += '''
  output wire logic [31:0] o_actual, // 移位后生成的保存索引
  output logic [31:0] o_reference, // 同一边沿保存的完整请求索引
  output wire logic [31:0] o_actual_pixel, // 请求寄存器保存的完整像素位置
  output logic [31:0] o_reference_pixel, // 同一写入边沿保存的完整像素参考值
  output wire logic o_equivalent // 已保存请求的逐位相等结果
);
  logic [31:0] request_index, request_pixel;
  logic observed_write = 1'b0;
  always_ff @(posedge i_clk) begin
    if (i_write) begin
      observed_write <= 1'b1;
      o_reference <= request_index;
      o_reference_pixel <= request_pixel;
    end
  end
'''
    model.write_text(header + '  conv_im2col_request_context #(' + parameter_connections +
                     ') u_context(\n' + connections + ''',
    .o_index(request_index), .o_request_pixel(request_pixel)
  );
  conv_request_index_register u_register (
    .i_clk, .i_write, .i_pixel(request_pixel), .i_short_pixel,
    .i_shift(i_index_shift), .i_reference(request_index), .o_index(o_actual), .o_pixel(o_actual_pixel)
  );
  assign o_equivalent = !observed_write ||
      {o_actual,o_actual_pixel} == {o_reference,o_reference_pixel};
endmodule
''')
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([
        ROOT / 'rtl/npu/conv/conv_im2col_request_context.sv',
        ROOT / 'rtl/npu/conv/conv_request_index_register.sv', model], ROOT)
    hashes = {str(p.relative_to(ROOT)): digest(p)
              for p in resolver['input_files'](sources, ROOT) if p.is_relative_to(ROOT)}
    report = {'source_sha256': hashes, 'formal': [], 'four_state': [],
              'compared_output_bits': {'window_index': 32, 'unscaled_pixel': 32}}
    port_netlist = out / 'port_widths.json'
    for width in (33, 35, 40):
        for line in (16, 128):
            for register in (0, 1):
                name = f'coord{width}_line{line}_register{register}'
                script, log = out / (name + '.ys'), out / (name + '.log')
                save_ports = ('write_json ' + shlex.quote(str(port_netlist)) + '\n'
                              if (width, line, register) == (35, 128, 1) else '')
                script.write_text(shlex.join(['read_slang', '--top', 'index_register_comparison',
                    '-DSYNTHESIS=1', '-DXILINX_FPGA=1', f'-Gp_coord_width={width}',
                    f'-Gp_line_bytes={line}', f'-Gp_register_descriptor={register}',
                    *map(str, sources)]) + '\n' +
                    'prep -top index_register_comparison -flatten\nopt_clean\ndffunmap\n' + save_ports +
                    'sat -verify -seq 2 -tempinduct -maxsteps 8 -prove o_equivalent 1\n')
                with log.open('w') as output:
                    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                    '--worker', str(script)], stdout=output, stderr=subprocess.STDOUT,
                                   check=True, timeout=180)
                if 'SUCCESS!' not in log.read_text():
                    raise RuntimeError('索引寄存器归纳证明没有完成')
                report['formal'].append({'coordinate_width': width, 'line_bytes': line,
                                        'register_descriptor': register, 'passed': True,
                                        'log_sha256': digest(log)})
                print('INDEX_REGISTER_FORMAL_PASS ' + name, flush=True)

    bench = out / 'tb.sv'
    input_names = ','.join(row[2] for row in inputs)
    ports = json.loads(port_netlist.read_text())['modules']['index_register_comparison']['ports']
    input_widths = {row[2]: len(ports[row[2]]['bits']) for row in inputs}
    if any(width <= 0 for width in input_widths.values()):
        raise RuntimeError('请求输入端口必须具有正位宽')
    input_width = sum(input_widths.values())
    report['input_widths'] = input_widths
    report['four_state_input_bits'] = input_width
    bench.write_text('''// 同一请求写入边沿比较二态和四态输入下的寄存结果。
module tb;
  localparam int p_coord_width = 35, p_line_bytes = 128;
  localparam bit p_register_descriptor = 1'b1;
  logic clk = 0, write_enable;
''' + '\n'.join('  ' + row[1] + ' ' + row[2] + ';' for row in inputs) + '''
  wire [31:0] actual, reference_value, actual_pixel, reference_pixel;
  wire equivalent;
  localparam int p_input_width = ''' + str(input_width) + ''';
  logic [p_input_width-1:0] stimulus;
  bit [p_input_width-1:0] seen_zero = '0, seen_one = '0, seen_x = '0, seen_z = '0;
  integer accepted_writes = 0, held_writes = 0, unknown_writes = 0;
  assign {''' + input_names + '''} = stimulus;
  index_register_comparison u_compare(
''' + connections + ''', .i_clk(clk), .i_write(write_enable),
    .o_actual(actual), .o_reference(reference_value), .o_actual_pixel(actual_pixel),
    .o_reference_pixel(reference_pixel), .o_equivalent(equivalent)
  );
  int unsigned random_state = 32'h429b1dc7;
  function automatic int unsigned random_word;
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
  endfunction
  initial begin
    if (p_input_width <= 0) $fatal(1, "INDEX_REGISTER_INPUT_WIDTH");
    stimulus = '0; write_enable = 1;
    #1; clk = 1; #1; clk = 0;
    for (integer sample = 0; sample < 8192; sample++) begin
      for (integer bit_index = 0; bit_index < p_input_width; bit_index++)
        stimulus[bit_index] = 1'(random_word());
      case (sample % 16)
        0: stimulus = '0;
        1: stimulus = '1;
        2: stimulus = 'x;
        3: stimulus = 'z;
        4,5,6,7: stimulus[sample % p_input_width] = 1'bx;
        8,9,10,11: stimulus[sample % p_input_width] = 1'bz;
        default: begin end
      endcase
      case (sample % 7)
        0,1,2,3: write_enable = 1'b1;
        4: write_enable = 1'b0;
        5: write_enable = 1'bx;
        6: write_enable = 1'bz;
        default: write_enable = 1'b1;
      endcase
      for (integer bit_index = 0; bit_index < p_input_width; bit_index++) begin
        case (stimulus[bit_index])
          1'b0: seen_zero[bit_index] = 1;
          1'b1: seen_one[bit_index] = 1;
          1'bx: seen_x[bit_index] = 1;
          1'bz: seen_z[bit_index] = 1;
        endcase
      end
      case (write_enable)
        1'b1: accepted_writes++;
        1'b0: held_writes++;
        default: unknown_writes++;
      endcase
      #1; clk = 1; #1;
      if ({actual,actual_pixel} !== {reference_value,reference_pixel})
        $fatal(1, "INDEX_REGISTER_MISMATCH sample=%0d actual=%h reference=%h", sample, actual, reference_value);
      clk = 0;
    end
    if ((&seen_zero) !== 1'b1 || (&seen_one) !== 1'b1 ||
        (&seen_x) !== 1'b1 || (&seen_z) !== 1'b1 ||
        accepted_writes == 0 || held_writes == 0 || unknown_writes == 0)
      $fatal(1, "INDEX_REGISTER_INPUT_COVERAGE");
    $display("INDEX_REGISTER_COVERAGE bits=%0d accepted=%0d held=%0d unknown_enable=%0d",
      p_input_width, accepted_writes, held_writes, unknown_writes);
    $display("INDEX_REGISTER_FOUR_STATE_PASS samples=8192");
    $finish;
  end
endmodule
''')
    for name, defines in [('generic', []), ('fpga', ['-DXILINX_FPGA=1']),
                          ('synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])]:
        binary, log = out / (name + '.vvp'), out / (name + '_four_state.log')
        with log.open('w') as output:
            subprocess.run(['iverilog', '-g2012', *defines, '-s', 'tb', '-o', str(binary),
                            *map(str, sources), str(bench)], stdout=output, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
            subprocess.run(['vvp', str(binary)], stdout=output, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        if 'INDEX_REGISTER_FOUR_STATE_PASS samples=8192' not in log.read_text():
            raise RuntimeError('索引寄存器四态比较没有完成')
        report['four_state'].append({'profile': name, 'samples': 8192,
                                     'input_bits': input_width, 'all_bits_seen_zero_one_x_z': True,
                                     'passed': True, 'log_sha256': digest(log)})
        print('INDEX_REGISTER_FOUR_STATE_PASS ' + name, flush=True)
    if any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise RuntimeError('验证期间 RTL 内容发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('INDEX_REGISTER_PASS formal=12 four_state=24576', flush=True)


if __name__ == '__main__':
    main()
