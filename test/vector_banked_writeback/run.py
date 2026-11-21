#!/usr/bin/env python3
"""验证字节银行写回的接收、字节地址、持续发送、暂停和错误恢复。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def execute(command, log):
    with log.open('w') as output:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, timeout=240)
    if result.returncode:
        raise RuntimeError(log.read_text()[-12000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root.resolve() / 'rtl/npu/conv/vector_engine.sv'
    original = source.read_text()
    module = re.search(r'^module vector_banked_writeback\b.*?^endmodule', original, re.M | re.S)[0]
    helper = out / 'vector_banked_writeback.sv'
    # 观察实际准备与复制状态，分别检查准备取消和部分字复制取消。
    observed_module = module.replace(
        'input  logic clk, rst_n,',
        'output logic monitor_prepared, monitor_copy_active, monitor_copy_word_fire,\n'
        '  input  logic clk, rst_n,')
    observed_module = observed_module.replace(
        '\nendmodule',
        '\n  assign monitor_prepared = request_prepared;\n'
        '  assign monitor_copy_active = copy_active;\n'
        '  assign monitor_copy_word_fire = copy_word_fire;\nendmodule')
    helper.write_text('`default_nettype none\n' + observed_module + '\n`default_nettype wire\n')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    report = {'source_sha256': source_hash,
              'test_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in [Path(__file__), HERE / 'main.cpp']},
              'module_sha256': hashlib.sha256(module.encode()).hexdigest(), 'runs': []}
    profiles = [(1, 32, 1), (2, 64, 1), (3, 32, 1), (16, 32, 1),
                (16, 64, 1), (16, 128, 1), (64, 64, 1), (3, 32, 0), (16, 64, 0)]
    for tile, bus, coalesce_bytes_only in profiles:
        folder = out / f'tile{tile}_bus{bus}_coalesce{coalesce_bytes_only}'
        folder.mkdir(exist_ok=True)
        execute([args.verilator, '--cc', '--exe', '--build', '--assert', '-j', args.jobs,
                 '--top-module', 'vector_banked_writeback', '-Wno-fatal',
                 '-DXILINX_FPGA=1', '-DNPU_SIM_ASSERT=1', f'-GTILE={tile}', f'-GBUS_WIDTH={bus}',
                 f'-Gp_coalesce_bytes_only={coalesce_bytes_only}',
                 '--Mdir', folder / 'obj', '-CFLAGS',
                 f'-std=c++17 -DTEST_TILE_SIZE={tile} -DTEST_BUS_WIDTH={bus} '
                 f'-DTEST_COALESCE_BYTES_ONLY={coalesce_bytes_only}',
                 helper, HERE / 'main.cpp'], folder / 'build.log')
        execute([folder / 'obj/Vvector_banked_writeback'], folder / 'run.log')
        text = (folder / 'run.log').read_text()
        matched = re.search(r'VECTOR_BANKED_WRITEBACK_PASS (.+)', text)
        if not matched:
            raise RuntimeError(f'缺少完整结果：{folder}')
        row = {k: int(v) for k, v in (item.split('=') for item in matched[1].split())}
        row['passed'] = True
        row['log_sha256'] = hashlib.sha256((folder / 'run.log').read_bytes()).hexdigest()
        report['runs'].append(row)
        print(text, end='', flush=True)
    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
