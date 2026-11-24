#!/usr/bin/env python3
"""证明窗口队列的占用、在途容量、准备位置和转发条件。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/conv_window_queue.sv')
PROPERTIES = '''
  logic observed_reset=1'b0;
  logic [p_frontend_outstanding:0][PTR_W-1:0] reference_present;
  assign reference_present[0]=head;
  for (genvar index=1; index<=p_frontend_outstanding; index++) begin : g_proof_position
    assign reference_present[index]=increment(reference_present[index-1]);
  end
  always_ff @(posedge clk) if (!rst_n) observed_reset<=1'b1;
  always_comb begin
    proof_invariant=!observed_reset || (
      count<=COUNT_W'(DEPTH) && int'(head)<DEPTH && int'(tail)<DEPTH &&
      int'(tail)==(int'(head)+int'(count))%DEPTH &&
      active_count<=p_active_width'(p_frontend_outstanding) && COUNT_W'(active_count)<=count &&
      present==reference_present[active_count] &&
      descriptor_forward==(accept && !descriptor_read_available && descriptor_read_index==tail) &&
      (!descriptor_prepared || failed || descriptor_available) && busy==(|count));
  end
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / SOURCE
    text = source.read_text()
    old = 'input wire logic frontend_rsp_last,frontend_error);'
    if text.count(old) != 1:
        raise RuntimeError('Queue interface could not be identified')
    text = text.replace(old, 'input wire logic frontend_rsp_last,frontend_error, output logic proof_invariant);', 1)
    text = text.replace('endmodule', PROPERTIES + 'endmodule', 1)
    proof = out / 'queue_invariants.sv'
    proof.write_text(text)
    report = dict(passed=True, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  input_constraints=['rst_n=0 at the first sampled edge'],
                  properties=['occupancy', 'frontend_capacity', 'pending_position',
                              'request_tail', 'forward_condition', 'prepared_available', 'busy_count'],
                  runs=[])
    for depth in (2, 3, 4, 7, 8):
        for outstanding in range(1, min(depth, 3) + 1):
            script = out / f'd{depth}_p{outstanding}.ys'
            log = script.with_suffix('.log')
            script.write_text(f'read_slang --top conv_window_queue -GDEPTH={depth} '
                f'-Gp_frontend_outstanding={outstanding} ' +
                shlex.join(map(str, (root / 'rtl/common/regfile.v', proof))) + '\n' +
                'prep -top conv_window_queue -flatten\nmemory_map\nasync2sync\nopt_clean\n' +
                'sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove proof_invariant 1 '
                '-maxsteps 10 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, timeout=90)
            output = log.read_text()
            if result.returncode or 'Induction step proven: SUCCESS!' not in output:
                raise RuntimeError('Queue invariant proof did not complete: ' + str(log))
            steps = int(re.findall(r'\[induction step (\d+)\]', output)[-1])
            report['runs'].append(dict(depth=depth, outstanding=outstanding,
                                       passed=True, induction_steps=steps))
    if report['source_sha256'] != hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError('Queue source changed during verification')
    (out / 'formal_summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('WINDOW_QUEUE_FORMAL_PASS', out / 'formal_summary.json', flush=True)


if __name__ == '__main__':
    main()
