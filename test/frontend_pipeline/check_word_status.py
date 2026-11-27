#!/usr/bin/env python3
"""验证描述符字标签比较在提交边沿前后保持相同结果，并检查四态传播。"""
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    model = out / 'comparison.sv'
    model.write_text('''
module word_status_comparison #(parameter int p_tag_width = 29) (
  input logic i_clk, input logic i_write,
  input logic [p_tag_width-1:0] i_target_tag, i_saved_tag, i_live_tag, i_response_tag,
  input logic i_saved_valid, i_live_valid, i_response_valid, i_padding,
  output logic [2:0] o_actual, o_reference,
  output logic o_equivalent
);
  logic [p_tag_width-1:0] target_q, saved_q, live_q;
  logic saved_valid_q, live_valid_q, padding_q;
  // 参考先保存完整标签和有效位，再按检查周期的数据来源进行比较。
  always_ff @(posedge i_clk) begin
    if (i_write) begin
      target_q <= i_target_tag;
      saved_q <= i_saved_tag;
      saved_valid_q <= i_saved_valid;
      live_q <= i_live_tag;
      live_valid_q <= i_live_valid;
      if (i_response_valid) begin
        live_q <= i_response_tag;
        live_valid_q <= 1'b1;
      end
      padding_q <= i_padding;
    end
  end
  assign o_reference[0] = saved_valid_q && target_q == saved_q;
  assign o_reference[1] = o_reference[0] || (live_valid_q && target_q == live_q);
  assign o_reference[2] = padding_q;
  conv_descriptor_word_status #(.p_tag_width(p_tag_width)) u_actual (
    .i_clk, .i_write, .i_target_tag, .i_saved_tag, .i_saved_valid,
    .i_live_tag, .i_live_valid, .i_response_tag, .i_response_valid, .i_padding,
    .o_saved_hit(o_actual[0]), .o_live_hit(o_actual[1]), .o_padding(o_actual[2])
  );
  assign o_equivalent = o_actual == o_reference;
endmodule
''')
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    source = ROOT / 'rtl/npu/conv/conv_descriptor_word_status.sv'
    sources = resolver['with_dependencies']([source, model], ROOT)
    hashes = {str(p.relative_to(ROOT)): digest(p)
              for p in resolver['input_files'](sources, ROOT) if p.is_relative_to(ROOT)}
    report = {'source_sha256': hashes, 'formal': [], 'four_state': {}}
    for width in (28, 29, 30):
        script = out / f'formal_{width}.ys'
        log = out / f'formal_{width}.log'
        script.write_text(shlex.join(['read_slang', '--top', 'word_status_comparison',
            '-DSYNTHESIS=1', f'-Gp_tag_width={width}', *map(str, sources)]) + '\n' +
            'prep -top word_status_comparison -flatten\nopt_clean\ndffunmap\n' +
            'sat -verify -seq 2 -tempinduct -maxsteps 8 -set-init-zero -prove o_equivalent 1\n')
        with log.open('w') as output:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=output, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        report['formal'].append({'tag_width': width, 'passed': True, 'log_sha256': digest(log)})
        print(f'WORD_STATUS_FORMAL_PASS tag_width={width}', flush=True)
    tb = out / 'four_state.sv'
    tb.write_text('''
module tb_word_status;
  logic clk = 0, write_enable;
  logic [28:0] target, saved, live, response;
  logic saved_valid, live_valid, response_valid, padding;
  wire [2:0] actual, reference_value;
  wire equivalent;
  int unsigned random_state = 32'h613c2a87;
  function automatic logic random_bit();
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    case (random_state[1:0])
      0: random_bit=1'b0; 1: random_bit=1'b1;
      2: random_bit=1'bx; default: random_bit=1'bz;
    endcase
  endfunction
  word_status_comparison u_comparison (
    .i_clk(clk), .i_write(write_enable), .i_target_tag(target), .i_saved_tag(saved),
    .i_live_tag(live), .i_response_tag(response), .i_saved_valid(saved_valid),
    .i_live_valid(live_valid), .i_response_valid(response_valid), .i_padding(padding),
    .o_actual(actual), .o_reference(reference_value), .o_equivalent(equivalent)
  );
  initial begin
    write_enable=1;target=0;saved=0;live=0;response=0;
    saved_valid=0;live_valid=0;response_valid=0;padding=0;
    #1;clk=1;#1;clk=0;
    for (int sample=0;sample<16384;sample++) begin
      for (int bit_index=0;bit_index<29;bit_index++) begin
        target[bit_index]=random_bit(); saved[bit_index]=random_bit();
        live[bit_index]=random_bit(); response[bit_index]=random_bit();
      end
      if (sample%8==0) begin target=29'(sample);saved=target;live=target;response=target;end
      if (sample%8==1) begin saved=target;live=target;response=target;end
      if (sample%8==2) begin target=29'(sample);saved=target;live=~target;response=target;end
      write_enable = sample%4==0 ? 1'b1 : random_bit();
      saved_valid=random_bit();live_valid=random_bit();response_valid=random_bit();padding=random_bit();
      #1;clk=1;#1;
      if (actual !== reference_value) $fatal(1,"WORD_STATUS_MISMATCH sample=%0d",sample);
      clk=0;
    end
    $display("WORD_STATUS_FOUR_STATE_PASS comparisons=16384");
    $finish;
  end
endmodule
''')
    binary = out / 'four_state.vvp'
    compile_log = out / 'four_state_compile.log'
    with compile_log.open('w') as output:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb_word_status', '-o', str(binary),
                        *map(str, sources), str(tb)], stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    log = out / 'four_state.log'
    with log.open('w') as output:
        subprocess.run(['vvp', str(binary)], stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    if 'WORD_STATUS_FOUR_STATE_PASS comparisons=16384' not in log.read_text():
        raise RuntimeError('四态比较没有完成')
    report['four_state'] = {'passed': True, 'comparisons': 16384, 'log_sha256': digest(log)}
    if any(digest(ROOT / path) != value for path, value in hashes.items()):
        raise RuntimeError('验证期间 RTL 内容发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('WORD_STATUS_FOUR_STATE_PASS comparisons=16384', flush=True)


if __name__ == '__main__':
    main()
