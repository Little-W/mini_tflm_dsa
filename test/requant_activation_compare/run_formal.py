#!/usr/bin/env python3
"""证明量化激活比较在完整结果与全部边界取值下保持严格有符号关系。"""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root / 'rtl/npu/writeback/vec_requant.sv'
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    models = []
    for name in ('LUT6_2', 'CARRY4'):
        model = re.search(r'^module ' + name + r'\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
        models.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S))
    model_file = out / 'xilinx_primitives.sv'
    model_file.write_text('\n'.join(models) + '\n')
    wrapper = out / 'activation_compare_formal.sv'
    wrapper.write_text('''module activation_compare_formal(
    input logic signed [35:0] i_value,
    input logic signed [31:0] i_minimum, i_maximum
);
    logic below, above;
    requant_activation_compare u_compare(
        .i_value(i_value), .i_minimum(i_minimum), .i_maximum(i_maximum),
        .o_below_minimum(below), .o_above_maximum(above));
    always_comb begin
        assert(below == (i_value < $signed({{4{i_minimum[31]}}, i_minimum})));
        assert(above == (i_value > $signed({{4{i_maximum[31]}}, i_maximum})));
    end
endmodule
''')
    summary = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
               'input_bits': 100, 'inputs_constrained': False, 'runs': []}
    for name, defines in [('fpga', '-D SYNTHESIS -D XILINX_FPGA'), ('generic', '-D SYNTHESIS -D ASIC_SYNTHESIS')]:
        script = out / (name + '.ys')
        script.write_text('read_slang --top activation_compare_formal ' + defines + ' ' +
                          ' '.join(shlex.quote(str(p)) for p in (source, wrapper, model_file)) + '\n'
                          'prep -top activation_compare_formal -flatten\n'
                          'chformal -lower\nopt -full\nsat -verify -prove-asserts -show-inputs\n')
        log = out / (name + '.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        summary['runs'].append({'implementation': name, 'passed': True,
                                'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
