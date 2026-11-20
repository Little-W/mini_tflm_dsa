#!/usr/bin/env python3
"""证明预选数据、端口地址及实际共享块写入数据的逐周期对应关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

from helpers import ROOT, SOURCES, make_wrapper
sys.path.insert(0, str(ROOT / 'test/ia_write_output_depth'))
from primitives import prepare_models


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wrapper = out / 'cache_shared.sv'
    ports = make_wrapper(wrapper, formal=True)
    model, model_info = prepare_models(out, names=('DSP48E1',))
    sources = [ROOT / path for path in SOURCES] + [ROOT / 'rtl/common/regfile.v',
               ROOT / 'rtl/common/pseudo_dual_port_ram.v', model, wrapper]
    hashes = {str(path): digest(path) for path in sources}
    hidden = [name for direction, _, name, _ in ports if direction == 'output' and name != 'o_properties']
    commands = ['read_slang --top cache_shared -DYOSYS=1 -DVERIFIC=1 -DSYNTHESIS=1 -DXILINX_FPGA=1 '
                '-Gp_shared_write_stage=1 ' + ' '.join(shlex.quote(str(p)) for p in sources),
                'prep -top cache_shared -flatten',
                'delete -output ' + ' '.join('cache_shared/' + name for name in hidden),
                'opt_clean -purge', 'memory_map', 'async2sync', 'opt_clean -purge',
                'select -module cache_shared',
                'sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 '
                '-set-def-inputs -set-def-formal -set-init-def -prove o_properties 31 -verify',
                'sat -seq 1 -tempinduct-inductonly -maxsteps 1 '
                '-set-def-inputs -set-def-formal -set-init-def -prove o_properties 31 -verify']
    script, log = out / 'formal.ys', out / 'formal.log'
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=180)
    text = log.read_text()
    passed = (result.returncode == 0 and 'SAT proof finished - no model found: SUCCESS!' in text
              and 'Induction step proven: SUCCESS!' in text)
    if not passed:
        raise RuntimeError('Shared write data proof did not complete: ' + str(log))
    if hashes != {str(p): digest(p) for p in sources}:
        raise RuntimeError('Sources changed during verification')
    report = dict(passed=True, source_sha256=hashes, primitive_models=model_info,
                  input_assumptions=['rst_n=0 at the first sampled edge'],
                  reset_base_steps=2, induction_steps=1, properties=5,
                  log_sha256=digest(log), script_sha256=digest(script))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
