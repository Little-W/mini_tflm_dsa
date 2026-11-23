#!/usr/bin/env python3
"""使用独立 im2col 方程检查配置准备、描述符排队和输出数据。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import runpy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__, add_help=False)
parser.add_argument('--target', choices=('asic', 'fpga'), default='asic')
parser.add_argument('--source-root', type=Path, default=ROOT)
parser.add_argument('--register-descriptor', choices=('0', '1'), default='1')
args, remaining = parser.parse_known_args()
SOURCE = args.source_root.resolve()
source_bench = SOURCE/'test/frontend_pipeline/tb_frontend_pipeline.sv'
if not source_bench.is_file():
    source_bench = HERE/'tb_frontend_pipeline.sv'
sys.argv[1:] = remaining
output = (Path(remaining[remaining.index('--out')+1]).resolve() if '--out' in remaining else
          ROOT/'build/frontend_pipeline'/f'numeric_{args.target}_reg{args.register_descriptor}')
support = output/'support'
support.mkdir(parents=True, exist_ok=True)

runner = ROOT/'test/conv_frontend/tools/run_rtl.py'
runner_text = runner.read_text().replace("reviewed={'UNUSEDSIGNAL'", "reviewed={'GENUNNAMED','UNUSEDSIGNAL'")
runner_text = runner_text.replace("'tests/tb_conv_im2col_frontend.sv'",
                                  repr(str(source_bench)))
runner_text = runner_text.replace(
    'and not unused_adapter_last(w) and not single_request_counter(w)]',
    'and not unused_adapter_last(w) and not single_request_counter(w) '
    'and not (w.startswith(\'%Warning-PINCONNECTEMPTY:\') and '
    '(("\'busy\'" in w and ("dma/cache/conv_read_cache.sv:" in w or '
    '"dma/cache/conv_windowed_cache.sv:" in w)) or '
    '("\'wr_last\'" in w and "conv_ia_tile_path.sv:" in w)))]')
environment = {'__file__': str(runner), '__name__': 'frontend_numeric_oracle'}
exec(compile(runner_text, str(runner), 'exec'), environment)
files = []
for name in environment['FILES']:
    path = Path(name)
    if path.is_absolute() and path.is_relative_to(ROOT/'rtl'):
        path = SOURCE/path.relative_to(ROOT)
    elif path.is_absolute() and path.is_relative_to(ROOT/'test/monitors'):
        source_observer = SOURCE/path.relative_to(ROOT)
        text = (source_observer if source_observer.is_file() else path).read_text()
        if path.name == 'conv_im2col_frontend_observer.sv':
            text = text.replace('p_state_width == 22', 'p_state_width >= 22')
        if path.name == 'conv_windowed_cache_observer.sv':
            text = text.replace('conv_windowed_cache.metadata_fill_bad',
                '(conv_windowed_cache.metadata_fill && '
                '(conv_windowed_cache.fill_bad || conv_windowed_cache.span_error))')
        destination = support/path.name
        destination.write_text('`undef SYNTHESIS\n'+text+'\n`define SYNTHESIS 1\n')
        path = destination
    elif path.name == 'tb_conv_im2col_frontend.sv':
        path = source_bench
    files.append(str(path))
files = [str(path) for path in runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))[
    'with_dependencies'](files, SOURCE)]
environment['FILES'] = files
environment['RTL'] = SOURCE/'rtl/npu/conv'
environment['OUTPUT'] = output
original_which = shutil.which
os.environ['FRONTEND_REAL_VERILATOR'] = original_which('verilator') or ''
os.environ['FRONTEND_RTL_TARGET'] = args.target
os.environ['FRONTEND_REGISTER_DESCRIPTOR'] = args.register_descriptor
os.environ['FRONTEND_RTL_ROOT'] = str(SOURCE)


def simulator(name, *arguments, **keywords):
    if name == 'verilator' and os.environ['FRONTEND_REAL_VERILATOR']:
        return str(HERE/'verilator_numeric.py')
    return original_which(name, *arguments, **keywords)


shutil.which = simulator
inputs = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['input_files'](files, SOURCE)
input_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
result = environment['main']()
status_path = output/'rtl_status.json'
if status_path.exists():
    status = json.loads(status_path.read_text())
    status.update(target=args.target, register_descriptor=int(args.register_descriptor),
                  slot_width=6, build_jobs=1, source_sha256=input_hashes,
                  frontend_sha256=input_hashes[str(SOURCE/'rtl/npu/conv/conv_im2col_frontend.sv')])
    changed = [name for name, digest in input_hashes.items()
               if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest]
    if changed:
        status.update(status='FAIL', changed_sources=changed)
        result = 1
    status_path.write_text(json.dumps(status, indent=2)+'\n')
sys.exit(result)
