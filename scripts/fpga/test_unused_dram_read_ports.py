#!/usr/bin/env python3
"""证明闲置分布式 RAM 读地址固定为零不会影响其余读写端口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return

    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    result = {'method': 'Official Yosys RAM models; sequential SAT induction',
              'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(), 'runs': []}
    for kind, address_width, data_width in (('RAM32M', 5, 2), ('RAM64M', 6, 1)):
        model = re.search(r'^module ' + kind + r'\b.*?^endmodule', library.read_text(),
                          re.MULTILINE | re.DOTALL).group(0)
        model = re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.DOTALL)
        model = model.replace('module ' + kind + ' (',
                              'module ' + kind + ' (output [255:0] formal_state,', 1)
        model = model.replace('endmodule',
                              'assign formal_state = {mem_a, mem_b, mem_c, mem_d};\nendmodule')
        model_path = folder / (kind + '.v')
        model_path.write_text(model + '\n')
        for unused in 'ABC':
            name = kind + '_' + unused
            lines = [f'module formal_ram(input clk, we, input [{address_width-1}:0] aa, ab, ac, ad,',
                     f'input [{data_width-1}:0] da, db, dc, dd);']
            for side in ('reference', 'actual'):
                lines.append(f'wire [255:0] {side}_state;')
                for port in 'ABCD':
                    lines.append(f'wire [{data_width-1}:0] {side}_{port};')
                connections = ['.WCLK(clk)', '.WE(we)', f'.formal_state({side}_state)']
                for port in 'ABCD':
                    address = f"{address_width}'b0" if side == 'actual' and port == unused else 'a' + port.lower()
                    connections += [f'.ADDR{port}({address})', f'.DI{port}(d{port.lower()})',
                                    f'.DO{port}({side}_{port})']
                lines.append(kind + ' ' + side + '(' + ', '.join(connections) + ');')
            lines.append('always @* begin')
            lines.append('assert(reference_state == actual_state);')
            for port in 'ABCD':
                if port != unused:
                    lines.append(f'assert(reference_{port} == actual_{port});')
            lines += ['end', 'endmodule']
            harness = folder / (name + '.sv')
            harness.write_text('\n'.join(lines) + '\n')
            script = folder / (name + '.ys')
            script.write_text('read_verilog -formal -sv -D VERIFIC ' +
                              ' '.join(shlex.quote(str(path)) for path in (model_path, harness)) + '\n'
                              'prep -top formal_ram -flatten\nchformal -lower\nmemory_map\nopt_clean\n'
                              'sat -seq 3 -tempinduct -prove-asserts -verify -set-init-zero -set-def-inputs\n')
            log_path = folder / (name + '.log')
            with log_path.open('w') as log:
                process = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                          '--out', str(folder), '--worker', str(script)],
                                         stdout=log, stderr=subprocess.STDOUT)
            log = log_path.read_text()
            passed = process.returncode == 0 and 'SUCCESS!' in log
            result['runs'].append({'memory_type': kind, 'unused_read_port': unused, 'passed': passed})
            result['passed'] = all(item['passed'] for item in result['runs'])
            (folder / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result['runs'][-1]), flush=True)
            if not passed:
                print(log[-8000:])
                raise SystemExit(1)


if __name__ == '__main__':
    main()
