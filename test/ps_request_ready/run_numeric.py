#!/usr/bin/env python3
"""逐周期比较部分和帧存储全部公开输出，并检查真实 INT32 帧读写与回放。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source_group as read_rtl_source, read_current_source as read_rtl_text

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
    parser.add_argument('--reference', default='d7cb67be')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--current-source', type=Path)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--profiles', nargs='+', default=['2048:6', '8192:7', '8192:9'])
    parser.add_argument('--max-frame-rows', type=int)
    parser.add_argument('--synthesis', action='store_true',
                        help='模拟 SYNTHESIS 条件下的硬件组合实现')
    parser.add_argument('--fpga', action='store_true', help='使用 FPGA 综合分支进行数值比较')
    args = parser.parse_args()
    if args.max_frame_rows is not None and args.max_frame_rows < 1:
        parser.error('--max-frame-rows must be positive')
    source_root = args.source_root.resolve()
    current_source = args.current_source.resolve() if args.current_source else source_root / SOURCE
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = read_rtl_text(current_source)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    for module in re.findall(r'\bmodule\s+(\w+)', original, re.M):
        original = re.sub(r'\b' + module + r'\b', module + '_reference', original)
    reference = out / 'reference.sv'
    reference.write_text(original)
    ports = port_declarations(current)
    outputs = [name for direction, _, name, _ in ports if direction == 'output']
    lines = [f'    {kind} ref_{name} {unpacked};' for direction, kind, name, unpacked in ports if direction == 'output']
    lines += ['    ps_frame_store_reference #(', ',\n'.join(f'        .{name}({name})' for name in PARAMETERS),
              '    ) u_reference (', ',\n'.join(f'        .{name}({"ref_" if direction == "output" else ""}{name})'
              for direction, _, name, _ in ports), '    );', '    always @(negedge clk) begin']
    lines += [f'        assert ({name} === ref_{name}) else $fatal(1, "PS output differs: {name}");'
              for name in outputs if name != 'ram_read_addr']
    lines += ['        for (int port_index = 0; port_index < 4; port_index++) begin',
              
              '                assert (ram_read_addr[port_index] === ref_ram_read_addr[port_index])',
              '                    else $fatal(1, "PS enabled read address differs: %0d", port_index);',
              '        end']
    lines += ['    end']
    checked = out / 'checked.sv'
    checked.write_text(current.replace('\nendmodule', '\n' + '\n'.join(lines) + '\nendmodule', 1))
    testbench_source = source_root / 'test/ps_channels/tb_store.sv'
    testbench = testbench_source
    if args.max_frame_rows is not None:
        testbench = out / 'tb_store.sv'
        updated, count = re.subn(r'localparam int p_max_frame_rows=.*?;',
                                f'localparam int p_max_frame_rows={args.max_frame_rows};',
                                testbench_source.read_text())
        if count != 1:
            raise RuntimeError('Expected one frame-row bound in the PS testbench')
        testbench.write_text(updated)
    sources = [source_root / 'rtl/npu/buffers/ia_ps_shared_ram.sv', source_root / 'rtl/common/regfile.v',
               checked, reference, testbench, source_root / 'rtl/common/parallel_prefix_add.sv']
    tracked_sources = list(dict.fromkeys([current_source, sources[0], sources[1],
                                        testbench_source, testbench, sources[5]]))
    summary = {'reference': args.reference, 'source_sha256': {str(p.relative_to(source_root) if p.is_relative_to(source_root) else p): digest(p) for p in
               tracked_sources}, 'compared_outputs': outputs,
               'all_public_outputs_compared_each_cycle': True,
               'max_frame_rows': args.max_frame_rows, 'synthesis': args.synthesis or args.fpga, 'fpga': args.fpga,
               'runs': []}
    import runpy
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolver(sources, source_root)
    for source in sources:
        name = str(source.relative_to(source_root) if source.is_relative_to(source_root) else source)
        summary['source_sha256'][name] = digest(source)
    for profile in args.profiles:
        bank_bytes, banks = map(int, profile.split(':'))
        folder = out / f'b{bank_bytes}_n{banks}'
        folder.mkdir(exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal', '-j', '1',
                   '--top-module', 'tb_ps_channel_store', '--Mdir', str(folder / 'obj'),
                   '-MAKEFLAGS', 'VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
                   f'-Gp_bank_bytes={bank_bytes}', f'-Gp_banks={banks}', *map(str, sources)]
        if args.synthesis or args.fpga:
            command.insert(1, '-DSYNTHESIS=1')
        if args.fpga:
            command.insert(1, '-DXILINX_FPGA=1')
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
    if summary['source_sha256'] != {name: digest(source_root / name) for name in summary['source_sha256']}:
        raise RuntimeError('RTL changed during verification')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
