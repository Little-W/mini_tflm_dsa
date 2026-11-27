#!/usr/bin/env python3
"""使用真实数据存储和现有写回用例，比较输出字节、掩码与逐周期公开结果。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='4927debf')
    parser.add_argument('--bus-width', type=int, choices=(32, 64), required=True)
    parser.add_argument('--s16-banks', type=int, default=4)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                       cwd=source, text=True).strip()
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    tops = ('rtl/npu/writeback/vec_s8_to_fifo.sv',
            'rtl/npu/writeback/vec_s16_to_fifo.sv')
    current = resolve([source/name for name in tops], source)

    # 每个参考模块及其依赖均从同一 Git 提交读取，统一重命名后独立实例化。
    snapshot = out/'reference_tree'
    snapshot.mkdir(exist_ok=True)
    archive = subprocess.check_output(['git', 'archive', revision, 'rtl'], cwd=source)
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        files.extractall(snapshot, filter='data')
    reference_paths = resolve([snapshot/name for name in tops], snapshot)
    originals = {str(path.relative_to(snapshot)): path.read_text() for path in reference_paths}
    names = set()
    for text in originals.values():
        code = re.sub(r'//[^\n]*|/\*.*?\*/', ' ', text, flags=re.S)
        names.update(re.findall(r'\b(?:module|package)\s+(\w+)\b', code))
    pattern = re.compile(r'\b('+'|'.join(sorted(map(re.escape, names), key=len, reverse=True))+r')\b')
    reference = []
    for name, text in originals.items():
        path = out/'reference'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pattern.sub(lambda match: match[0]+'_reference', text))
        reference.append(path)

    original_bench = ROOT/'test/writeback_bus/tb_writeback_bus.sv'
    bench_text = original_bench.read_text()
    bench_text = bench_text.replace('vec_s8_to_fifo_ref ', 'vec_s8_to_fifo_reference ')
    bench_text = bench_text.replace('vec_s16_to_fifo_ref ', 'vec_s16_to_fifo_reference ')
    for module in ('vec_s16_to_fifo', 'vec_s16_to_fifo_reference'):
        expression = module+' #(.VLEN(VLEN), .BANKS(BANKS), .BUS_WIDTH(BUS_WIDTH))'
        replacement = (module+' #(.VLEN(VLEN), .BANKS('+str(args.s16_banks)+'), '
                       '.BUS_WIDTH(BUS_WIDTH), .p_precomputed_watermark(1))')
        if bench_text.count(expression) != 1:
            raise ValueError('需要唯一的十六位 FIFO 实例：'+module)
        bench_text = bench_text.replace(expression, replacement)
    bench_text = bench_text.replace('.in_vec_s16, .oa_fifo_req(',
        ".in_vec_s16, .i_ready_bank_threshold(32'd"+str(args.s16_banks-1)+"), .oa_fifo_req(")
    anchor = '    always @(posedge clk) if (rst_n) begin\n'
    bench_text = bench_text.replace(anchor, anchor+
        '        assert (s16_fifo.o_issue_full === ref_s16_full)\n'
        '            else $fatal(1, "S16 issue capacity differs from the selected output capacity");\n')
    bench = out/'tb_writeback_bus.sv'
    bench.write_text(bench_text)
    checked = [*current, original_bench, Path(__file__), ROOT/'scripts/rtl/source_files.py']
    hashes = {str(path): digest(path) for path in checked}
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
               '--top-module', 'tb_writeback_bus', f'-DTB_BUS_WIDTH={args.bus_width}',
               '-DWRITEBACK_COMPARE_REFERENCE', '-CFLAGS', '-std=c++20 -O1',
               '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
               '--Mdir', str(out/'obj'), '-j', str(args.jobs),
               *map(str, current), *map(str, reference), str(bench)]
    with (out/'build.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run([str(out/'obj/Vtb_writeback_bus')],
                         capture_output=True, text=True, timeout=120)
    (out/'run.log').write_text(run.stdout+run.stderr)
    match = re.search(r'WRITEBACK_BUS_PASS bus_width=(\d+) cases=(\d+) checked_bytes=(\d+)', run.stdout)
    result = dict(passed=run.returncode == 0 and match is not None,
                  bus_width=args.bus_width, s16_banks=args.s16_banks,
                  precomputed_watermark=1, reference_commit=revision,
                  source_sha256=hashes, reference_sha256={
                      name: hashlib.sha256(text.encode()).hexdigest() for name, text in originals.items()},
                  generated_test_sha256=digest(bench), command=command,
                  source_unchanged=all(digest(Path(path)) == value for path, value in hashes.items()))
    if match:
        result.update(cases=int(match[2]), checked_bytes=int(match[3]))
    result['passed'] &= result['source_unchanged']
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise RuntimeError(run.stdout+run.stderr)


if __name__ == '__main__':
    main()
