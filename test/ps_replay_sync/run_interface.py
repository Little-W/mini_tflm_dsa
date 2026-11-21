#!/usr/bin/env python3
"""逐周期比较部分和帧存储的全部公开输出，并检查随机 INT32 重放数据。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test/ia_timing'))
from run_interface import port_declarations

SOURCE = Path('rtl/npu/ps_compact/ps_frame_store.sv')
PARAMETERS = ('MAX_FRAME_ROWS', 'FRAME_COUNT', 'POOL_BYTES', 'BANK_BYTES', 'DECODE_FIFO_ROWS',
              'EXTERNAL_RAM', 'p_fixed_ps_channels', 'DIRECTORY_ROWS', 'RAM_ADDR_BITS')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='653477ed')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--profiles', nargs='+', default=['2048:6', '8192:7', '8192:9'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    for module in re.findall(r'^module\s+(\w+)', original, re.M):
        original = re.sub(r'\b' + module + r'\b', module + '_reference', original)
    reference = out / 'reference.sv'
    reference.write_text(original)
    ports = port_declarations(current)
    outputs = [name for direction, _, name, _ in ports if direction == 'output']
    lines = [f'    {kind} ref_{name} {unpacked};' for direction, kind, name, unpacked in ports if direction == 'output']
    lines += ['    ps_frame_store_reference #(', ',\n'.join(f'        .{name}({name})' for name in PARAMETERS),
              '    ) u_reference (', ',\n'.join(f'        .{name}({"ref_" if direction == "output" else ""}{name})'
              for direction, _, name, _ in ports), '    );', '    always @(negedge clk) begin']
    lines += [f'        assert ({name} === ref_{name}) else $fatal(1, "PS output differs: {name}");' for name in outputs]
    lines += ['    end']
    checked = out / 'checked.sv'
    checked.write_text(current.replace('\nendmodule', '\n' + '\n'.join(lines) + '\nendmodule', 1))
    sources = [ROOT / 'rtl/npu/buffers/ia_ps_shared_ram.sv', ROOT / 'rtl/common/regfile.v',
               checked, reference, ROOT / 'test/ps_channels/tb_store.sv',
               ROOT / 'rtl/common/parallel_prefix_add.sv']
    summary = {'reference': args.reference, 'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in
               [ROOT / SOURCE, sources[0], sources[1], sources[4], sources[5]]}, 'compared_outputs': outputs, 'runs': []}
    for profile in args.profiles:
        bank_bytes, banks = map(int, profile.split(':'))
        folder = out / f'b{bank_bytes}_n{banks}'
        folder.mkdir(exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal', '-j', '1',
                   '--top-module', 'tb_ps_channel_store', '--Mdir', str(folder / 'obj'),
                   f'-Gp_bank_bytes={bank_bytes}', f'-Gp_banks={banks}', *map(str, sources)]
        with (folder / 'compile.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        run = subprocess.run([str(folder / 'obj/Vtb_ps_channel_store')], cwd=ROOT, text=True, capture_output=True)
        (folder / 'run.log').write_text(run.stdout + run.stderr)
        match = re.search(r'PS_CHANNEL_STORE_PASS (.*)', run.stdout)
        if run.returncode or not match:
            raise RuntimeError(run.stdout + run.stderr)
        row = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match[1])}
        row.update(passed=True, binary_sha256=digest(folder / 'obj/Vtb_ps_channel_store'))
        summary['runs'].append(row)
        print(json.dumps(row), flush=True)
    if summary['source_sha256'] != {name: digest(ROOT / name) for name in summary['source_sha256']}:
        raise RuntimeError('RTL changed during verification')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
