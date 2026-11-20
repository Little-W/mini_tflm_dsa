#!/usr/bin/env python3
"""对任意能力位图证明允许写入的银行数量可由所选位宽完整保存。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from prepare_measurement import ROOT, SOURCE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    first = source.index('    localparam int p_shared_count_width =')
    expression = source[first:source.index(';', first) + 1]
    expression = expression.replace('localparam int', 'wire [2:0]')
    actual_store = "cfg_shared_ia_banks <= 32'(shared_ia_banks_next[p_shared_count_width-1:0]);"
    assert actual_store in source
    model = out / 'proof.sv'
    model.write_text("""module proof(input [31:0] SHARED_IA_BANK_MASK,
    input [31:0] shared_ia_banks_next, output correct);
""" + expression + """
    wire accepted = (shared_ia_banks_next < 32) &&
        SHARED_IA_BANK_MASK[shared_ia_banks_next[4:0]];
    wire [31:0] saved_value =
        p_shared_count_width == 5 ? {27'd0, shared_ia_banks_next[4:0]} :
        p_shared_count_width == 4 ? {28'd0, shared_ia_banks_next[3:0]} :
        p_shared_count_width == 3 ? {29'd0, shared_ia_banks_next[2:0]} :
        p_shared_count_width == 2 ? {30'd0, shared_ia_banks_next[1:0]} :
                                    {31'd0, shared_ia_banks_next[0]};
    assign correct = !accepted || saved_value == shared_ia_banks_next;
endmodule
""")
    script = out / 'proof.ys'
    script.write_text(f'read_slang --top proof {model}\n'
                      'prep -top proof -flatten\n'
                      'sat -verify -prove correct 1 -show-inputs\n')
    log = out / 'proof.log'
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
    report = {'passed': True, 'arbitrary_mask_bits': 32, 'arbitrary_value_bits': 32,
              'input_assumptions': [],
              'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'proof_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
              'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
