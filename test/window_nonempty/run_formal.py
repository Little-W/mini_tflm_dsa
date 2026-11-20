#!/usr/bin/env python3
"""证明准备完成且可用的窗口描述符始终占用队列位置。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/conv_window_queue.sv')
OLD = '  assign frontend_valid=enable && !configure && !failed && !frontend_error &&\n'
NEW = '''  // 准备项始终占用队列位置，显式非空条件使空闲配置与前端发送保持互斥。
  assign frontend_valid=enable && !configure && !failed && !frontend_error && busy &&
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8bd4b00b')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    original = subprocess.check_output(['git', 'show', args.reference + ':' + str(SOURCE)], cwd=ROOT, text=True)
    assert current.count(NEW) == 1 and current.replace(NEW, OLD, 1) == original
    observation = '''
  logic observed_reset = 1'b0;
  always_ff @(posedge clk) if (!rst_n) observed_reset <= 1'b1;
  assign proof_invariant = !observed_reset || !descriptor_prepared || failed || busy;
'''
    observed = original.replace('  input logic clk,rst_n,configure,enable,',
        '  output logic proof_invariant,\n  input logic clk,rst_n,configure,enable,', 1)
    observed = observed.replace('\nendmodule', observation + '\nendmodule', 1)
    source = out / 'observed.sv'; source.write_text(observed)
    cases = []
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    for depth in (2, 3, 4, 7, 8):
        script, log = out / f'depth{depth}.ys', out / f'depth{depth}.log'
        script.write_text(f'read_slang --top conv_window_queue -GDEPTH={depth} {source}\n' +
            'prep -top conv_window_queue -flatten\nmemory_map\nasync2sync\nopt_clean\n' +
            'select -module conv_window_queue\n' +
            'sat -verify -seq 2 -tempinduct -maxsteps 8 -prove proof_invariant 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        assert 'Induction step proven: SUCCESS!' in log.read_text()
        cases.append(dict(depth=depth, passed=True, script_sha256=digest(script), log_sha256=digest(log)))
        print(f'DEPTH={depth}: induction passed', flush=True)
    result = dict(passed=True, reference=args.reference, source_sha256=digest(ROOT / SOURCE),
        reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        unchanged_outside_frontend_valid=True, actual_module_state_updates=True,
        inputs_constrained=False, property='After reset, a prepared descriptor that is not failed has a nonempty queue',
        observed_source_sha256=digest(source), cases=cases)
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
