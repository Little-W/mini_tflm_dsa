#!/usr/bin/env python3
"""检查坐标比较分组的完整二值输入和四态组合行为。"""
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
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=ROOT)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-rev', default='ef0dc75')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    repository, source_root, out = args.repository.resolve(), args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(repository / 'test'))
    from rtl_reference import read_rtl_source

    reference = read_rtl_source(args.reference_rev + ':' + SOURCE.as_posix(), cwd=repository, text=True)
    source_path = source_root / 'rtl/npu/conv/vector_coordinate_bound.sv'
    source = source_path.read_text()
    source_hash = digest(source_path)
    helper_hashes = {}
    models = []
    for name, text in [('reference', reference), ('candidate', source)]:
        helper = re.search(r'^module vector_coordinate_bound\b.*?^endmodule', text, re.M | re.S)[0]
        helper_hashes[name] = hashlib.sha256(helper.encode()).hexdigest()
        model = out / (name + '.sv')
        model.write_text(helper.replace('module vector_coordinate_bound (', 'module coordinate_' + name + ' (') + '\n')
        models.append(model)
    comparison = out / 'comparison.sv'
    comparison.write_text('''module comparison (
  input logic signed [33:0] i_coordinate,
  input logic [15:0] i_limit,
  output logic equal
);
  logic reference_value, candidate_value, integer_relation;
  coordinate_reference u_reference (.i_coordinate, .i_limit, .o_in_bounds(reference_value));
  coordinate_candidate u_candidate (.i_coordinate, .i_limit, .o_in_bounds(candidate_value));
  assign integer_relation = i_coordinate >= 34'sd0 &&
      i_coordinate < $signed({18'd0, i_limit});
  assign equal = (reference_value == candidate_value) && (candidate_value == integer_relation);
endmodule
''')
    script = out / 'formal.ys'
    script.write_text('\n'.join([
        'read_slang --top comparison ' + ' '.join(shlex.quote(str(p)) for p in models + [comparison]),
        'prep -top comparison -flatten', 'opt_clean',
        'sat -verify -prove equal 1 -show-inputs -show-outputs',
    ]) + '\n')
    with (out / 'formal.log').open('w') as log:
        formal = subprocess.run([sys.executable, repository / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                                stdout=log, stderr=subprocess.STDOUT, cwd=repository)
    if formal.returncode:
        raise RuntimeError('坐标比较形式检查未通过')
    bench = out / 'four_state.sv'
    bench.write_text('''module tb;
  logic signed [33:0] coordinate;
  logic [15:0] limit;
  wire reference_value, candidate_value;
  integer seed, unused_seed, sample_index, bit_index, checks;
  coordinate_reference u_reference (.i_coordinate(coordinate), .i_limit(limit), .o_in_bounds(reference_value));
  coordinate_candidate u_candidate (.i_coordinate(coordinate), .i_limit(limit), .o_in_bounds(candidate_value));
  task check;
    #1;
    if (candidate_value !== reference_value)
      $fatal(1, "coordinate=%h limit=%h reference=%b candidate=%b", coordinate, limit, reference_value, candidate_value);
    checks=checks+1;
  endtask
  initial begin
    seed=32'h26a1b783; unused_seed=$urandom(seed); checks=0;
    for (sample_index=0;sample_index<131072;sample_index=sample_index+1) begin
      coordinate={18'd0, 16'($urandom())}; limit=16'($urandom());
      case (sample_index%8)
        0: begin coordinate={ $urandom(), $urandom() }; end
        1: begin coordinate=$signed({18'd0,limit})-34'sd1; end
        2: begin coordinate=$signed({18'd0,limit}); end
        3: begin coordinate[$urandom()%16]=1'bx; end
        4: begin limit[$urandom()%16]=1'bz; end
        5: begin
          for (bit_index=0;bit_index<4;bit_index=bit_index+1) begin
            coordinate[$urandom()%34]=1'bz; limit[$urandom()%16]=1'bx;
          end
        end
        6: begin coordinate[33:16]='x; end
        7: begin coordinate[15:0]=limit; coordinate[$urandom()%16]=1'bx; end
      endcase
      check();
    end
    coordinate='x; limit='0; check();
    coordinate='z; limit='1; check();
    coordinate='0; limit='x; check();
    coordinate='0; limit='z; check();
    coordinate='1; limit='x; check();
    coordinate='1; limit='z; check();
    coordinate={18'd0,16'hffff}; limit='1; check();
    coordinate={18'd0,16'hfffe}; limit='1; check();
    $display("COORDINATE_GROUPS_PASS checks=%0d",checks);
    $finish;
  end
endmodule
''')
    binary = out / 'four_state.vvp'
    for name, command in [
        ('four_state_build', [args.iverilog, '-g2012', '-s', 'tb', '-o', str(binary), *map(str, models), str(bench)]),
        ('four_state', [args.vvp, str(binary)]),
    ]:
        result = subprocess.run(command, cwd=repository, capture_output=True, text=True, timeout=120)
        (out / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('坐标比较四态检查未通过：' + name)
    count = re.search(r'COORDINATE_GROUPS_PASS checks=(\d+)', (out / 'four_state.log').read_text())
    assert count is not None
    assert digest(source_path) == source_hash
    report = {
        'passed': True, 'reference_revision': args.reference_rev,
        'source_sha256': source_hash, 'helper_sha256': helper_hashes,
        'binary_proof': 'All 34-bit coordinates and 16-bit limits; both implementations equal the signed integer range relation',
        'inputs_constrained': False, 'strict_four_state_checks': int(count[1]),
        'test_sha256': digest(Path(__file__).resolve()),
        'log_sha256': {name: digest(out / name) for name in ['formal.log', 'four_state_build.log', 'four_state.log']},
    }
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
