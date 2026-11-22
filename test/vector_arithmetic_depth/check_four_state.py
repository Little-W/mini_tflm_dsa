#!/usr/bin/env python3
"""比较实际舍入模块的四态输出，覆盖全部移位量与两个寄存配置。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_round_shift.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-ref', default='ef0dc75')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.reference_root:
        reference_path = args.reference_root.resolve() / SOURCE
        reference = str(args.reference_root.resolve())
    else:
        reference = subprocess.check_output(['git', 'rev-parse', args.reference_ref],
                                            cwd=ROOT, text=True).strip()
        reference_path = out / 'reference_input.sv'
        reference_path.write_bytes(subprocess.check_output(
            ['git', 'show', f'{reference}:{SOURCE}'], cwd=ROOT))
    originals = {'reference': reference_path,
                 'current': args.source_root.resolve() / SOURCE}
    sources = []
    hashes = {label: digest(path) for label, path in originals.items()}
    for label, original in originals.items():
        target = out / (label + '.sv')
        text, count = re.subn(r'\bmodule\s+vector_round_shift\b',
                             'module round_' + label, original.read_text())
        assert count == 1
        target.write_text(text)
        sources.append(target)
    tb = out / 'tb.sv'
    tb.write_text('''module tb;
  reg clk=0;
  reg signed [63:0] value, known;
  reg [5:0] amount;
  wire signed [63:0] old_result[2], new_result[2], old_floor[2], new_floor[2];
  integer checks=0, seed=32'h174be82a;
  for(genvar stage=0;stage<2;stage++) begin:g_stage
    round_reference #(.REGISTER_MIDDLE(stage)) u_old(
      .clk(clk),.value(value),.amount(amount),.result(old_result[stage]),.floor_value(old_floor[stage]));
    round_current #(.REGISTER_MIDDLE(stage)) u_new(
      .clk(clk),.value(value),.amount(amount),.result(new_result[stage]),.floor_value(new_floor[stage]));
  end
  task check;
    begin
      #1;clk=1;#1;
      for(integer stage=0;stage<2;stage++) begin
        if(old_result[stage]!==new_result[stage] || old_floor[stage]!==new_floor[stage])
          $fatal(1,"Four-state mismatch stage=%0d value=%h amount=%b old=%h new=%h",
                 stage,value,amount,old_result[stage],new_result[stage]);
      end
      checks=checks+1;clk=0;#1;
    end
  endtask
  initial begin
    for(integer sample=0;sample<256;sample++) begin
      known={$random(seed),$random(seed)};
      if(sample==0)known='0;
      if(sample==1)known='1;
      if(sample==2)known=64'h8000000000000000;
      if(sample==3)known=64'h7fffffffffffffff;
      for(integer shift=0;shift<64;shift++) begin
        amount=6'(shift);value=known;check();
        if(sample<4)begin
          for(integer bit_i=0;bit_i<64;bit_i++)begin
            value=known;value[bit_i]=1'bx;check();
            value=known;value[bit_i]=1'bz;check();
          end
        end
      end
      for(integer bit_i=0;bit_i<6;bit_i++)begin
        value=known;amount='0;amount[bit_i]=1'bx;check();
        amount='1;amount[bit_i]=1'bz;check();
      end
    end
    for(integer shift=0;shift<64;shift++)begin
      amount=6'(shift);value='x;check();value='z;check();
    end
    $display("ROUND_FOUR_STATE_PASS checks=%0d configurations=2 outputs=2",checks);
    $finish;
  end
endmodule
''')
    executable = out / 'simulation.vvp'
    command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
               *map(str, sources), str(tb)]
    with (out / 'build.log').open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(['vvp', str(executable)], text=True, capture_output=True, timeout=120)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    match = re.search(r'ROUND_FOUR_STATE_PASS checks=(\d+)', result.stdout)
    assert result.returncode == 0 and match, result.stdout + result.stderr
    assert hashes == {label: digest(path) for label, path in originals.items()}
    report = {'passed': True, 'strict_four_state_equivalence': True,
              'checks': int(match[1]), 'register_configurations': [0, 1],
              'outputs': ['result', 'floor_value'], 'source_sha256': hashes,
              'reference_revision': reference,
              'source_root': str(args.source_root.resolve()),
              'testbench_sha256': digest(tb), 'run_log_sha256': digest(out / 'run.log'),
              'build_command': command}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': report['checks']}))


if __name__ == '__main__':
    main()
