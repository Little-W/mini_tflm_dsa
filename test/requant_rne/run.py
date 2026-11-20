#!/usr/bin/env python3
"""Compare production INT8 and INT16 writeback arithmetic with integer division."""
import argparse
import json
from pathlib import Path
import re
import subprocess

here = Path(__file__).resolve().parent
root = here.parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--verilator', default='verilator')
p.add_argument('--xilinx', action='store_true')
a = p.parse_args()
out = a.out.resolve()
out.mkdir(parents=True, exist_ok=True)
primitive_options = []
if a.xilinx:
    import pyosys
    library = Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    library_source = library.read_text()
    models = [re.search(r'^module '+name+r'\b.*?^endmodule', library_source,
                        re.MULTILINE | re.DOTALL).group(0) for name in ('LUT6_2','DSP48E1','FDRE','CARRY4')]
    model_file = out/'xilinx_primitives.sv'
    model_file.write_text('\n'.join(models)+'\n')
    primitive_options = ['-DSYNTHESIS',str(model_file)]
cmd = [a.verilator, '--cc', '--exe', '--build', '-j', '1', '-Wno-fatal',
       '--top-module', 'tb_requant_rne', '--Mdir', str(out/'obj'),
       str(root/'rtl/npu/writeback/vec_requant.sv'),
       str(root/'rtl/npu/conv/vector_scalar_multiplier.sv'),
       str(root/'rtl/common/REGFILE.v'),
       str(root/'rtl/npu/writeback/vec_requant_s64.sv'),
       str(here/'tb_requant_rne.sv'), *primitive_options, str(here/'main.cpp')]
with (out/'build.log').open('w') as stream:
    subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT, check=True)
r = subprocess.run([str(out/'obj/Vtb_requant_rne')], text=True, capture_output=True)
(out/'run.log').write_text(r.stdout+r.stderr)
(out/'summary.json').write_text(json.dumps({'passed': r.returncode == 0,
    'outputs': 320000, 'variants': 4, 'command': cmd, 'log': r.stdout+r.stderr}, indent=2)+'\n')
print(r.stdout+r.stderr, end='')
raise SystemExit(r.returncode)
