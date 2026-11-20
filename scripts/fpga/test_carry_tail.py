#!/usr/bin/env python3
"""使用 Yosys CARRY4 原语模型证明未观察尾部位的输入独立性。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import pyosys
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module CARRY4\b.*?^endmodule', library.read_text(), re.MULTILINE | re.DOTALL).group(0)
    model = re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.DOTALL)
    model_path = folder / 'yosys_carry4.sv'
    model_path.write_text(model + '\n')
    design = folder / 'carry_tail_miter.sv'
    design.write_text('''module carry_tail_miter #(
    parameter integer OBSERVED_BITS = 1
) (
    input wire [3:0] di,
    input wire [3:0] s,
    input wire [3:0] alternate_di,
    input wire [3:0] alternate_s,
    input wire ci,
    input wire cyinit,
    output wire equal_outputs
);
    wire [3:0] reference_o;
    wire [3:0] reference_co;
    wire [3:0] candidate_o;
    wire [3:0] candidate_co;
    wire [3:0] candidate_di = {alternate_di[3:OBSERVED_BITS], di[OBSERVED_BITS-1:0]};
    wire [3:0] candidate_s = {alternate_s[3:OBSERVED_BITS], s[OBSERVED_BITS-1:0]};
    CARRY4 u_reference (.DI(di), .S(s), .CI(ci), .CYINIT(cyinit),
                        .O(reference_o), .CO(reference_co));
    CARRY4 u_candidate (.DI(candidate_di), .S(candidate_s), .CI(ci), .CYINIT(cyinit),
                        .O(candidate_o), .CO(candidate_co));
    assign equal_outputs = (reference_o[OBSERVED_BITS-1:0] == candidate_o[OBSERVED_BITS-1:0]) &&
                           (reference_co[OBSERVED_BITS-1:0] == candidate_co[OBSERVED_BITS-1:0]);
endmodule
''')
    worker = Path(__file__).with_name('open_fpga_synth.py')
    summary = {'yosys_library_sha256': digest(library), 'model_sha256': digest(model_path),
               'miter_sha256': digest(design), 'all_lower_o_and_co_bits_checked': True,
               'alternate_tail_inputs_may_be_undefined': True, 'cases': []}
    for observed in (1, 2, 3):
        script = folder / f'observed_{observed}.ys'
        script.write_text('\n'.join([
            'read_verilog -formal -sv ' + shlex.quote(str(model_path)),
            'read_verilog -formal -sv ' + shlex.quote(str(design)),
            f'chparam -set OBSERVED_BITS {observed} carry_tail_miter',
            'hierarchy -check -top carry_tail_miter', 'prep -top carry_tail_miter -flatten',
            'sat -verify -prove equal_outputs 1 -enable_undef -set-def di -set-def s -set-def ci -set-def cyinit',
        ]) + '\n')
        with script.with_suffix('.log').open('w') as log:
            subprocess.run([sys.executable, str(worker), '--worker', str(script)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        summary['cases'].append({'observed_low_bits': observed, 'removed_high_bits': 4-observed,
                                 'script_sha256': digest(script), 'passed': True})
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
