#!/usr/bin/env python3
"""检查生产权重缓存的容量、端口行为以及 ASIC SRAM 实现。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOP = 'kernel_loader_buffer'
SOURCES = ('rtl/npu/loaders/kernel_loader_buffer.sv', 'rtl/common/regfile.v',
           'asic/rtl/smic40_sram_1r1w.sv')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value):
    return int(value, 2) if isinstance(value, str) else value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    snapshot = out / 'sources'
    snapshot.mkdir(parents=True, exist_ok=True)
    sources, hashes = [], {}
    for name in SOURCES:
        target = snapshot / Path(name).name
        target.write_bytes((source_root / name).read_bytes())
        sources.append(target)
        hashes[name] = sha(target)
    blackbox = ROOT / 'test/requant_group_buffer_npu/sram_blackboxes.sv'
    target = snapshot / blackbox.name
    target.write_bytes(blackbox.read_bytes())
    sources.append(target)
    hashes[str(blackbox.relative_to(ROOT))] = sha(target)
    report = dict(passed=False, source_sha256=hashes, size=16, data_width=16,
                  logical_slots=2, physical_slots=3, logical_storage_bits=12288,
                  profiles=[])
    for mode in ('asic', 'fpga'):
        folder = out / mode
        folder.mkdir(exist_ok=True)
        script, log, netlist = folder / 'run.ys', folder / 'run.log', folder / 'netlist.json'
        define = '-DASIC_SYNTHESIS=1 -DASIC_SRAM=1' if mode == 'asic' else '-DXILINX_FPGA=1'
        commands = [f'read_slang --top {TOP} -DSYNTHESIS=1 {define} -GSIZE=16 -GDATA_WIDTH=16 '
                    '--blackboxed-module RAMTP128X16 --blackboxed-module RAMTP1024X16 ' +
                    shlex.join(map(str, sources)),
                    f'hierarchy -check -top {TOP}', 'proc', 'flatten', 'opt', 'memory_dff',
                    'memory_collect', 'opt_clean', 'check -assert',
                    'write_json ' + shlex.quote(str(netlist))]
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        module = json.loads(netlist.read_text())['modules'][TOP]
        cells = module['cells']
        macros = [(name, cell) for name, cell in cells.items() if cell['type'].startswith('RAMTP')]
        memories = [(name, cell) for name, cell in cells.items() if cell['type'] == '$mem_v2']
        matrix_memories = [(name, cell) for name, cell in memories
                           if 'g_row_storage.' in name or 'g_column_storage.' in name]
        assert not any('latch' in cell['type'].lower() for cell in cells.values())
        flip_flops = sum(len(cell['connections']['Q']) for cell in cells.values()
                         if cell['type'].startswith(('$dff', '$sdff', '$adff')))
        if mode == 'asic':
            assert len(macros) == 16, len(macros)
            assert all(cell['type'] == 'RAMTP128X16' for _, cell in macros)
            assert not matrix_memories
            result = dict(macro_count=16, matrix_inferred_memories=0,
                          matrix_storage_bits=12288, physical_storage_bits=16 * 128 * 16,
                          register_bits_outside_memories=flip_flops,
                          synchronous_read=True, synchronous_write=True,
                          read_ports_per_column=1, write_ports_per_column=1,
                          same_address_read='old data', storage_implementation='SRAM')
        else:
            assert not macros
            result = None
        if mode == 'fpga':
            assert len(matrix_memories) == 16, len(matrix_memories)
            capacity = 0
            for column in range(16):
                matched = [(name, cell) for name, cell in matrix_memories
                           if f'g_column_storage.g_column_ram[{column}].' in name]
                assert len(matched) == 1, (column, len(matched))
                _, memory = matched[0]
                params = memory['parameters']
                assert number(params['WIDTH']) == 16
                assert number(params['SIZE']) == 48
                assert number(params['RD_PORTS']) == 1
                assert number(params['RD_CLK_ENABLE']) == 1
                assert number(params['WR_PORTS']) == 1
                assert number(params['WR_CLK_ENABLE']) == 1
                assert number(params['RD_TRANSPARENCY_MASK']) == 0
                assert number(params['RD_COLLISION_X_MASK']) == 0
                capacity += number(params['WIDTH']) * number(params['SIZE'])
            assert capacity == 12288
            result = dict(macro_count=0, matrix_inferred_memories=16,
                          matrix_storage_bits=capacity, register_bits_outside_memories=flip_flops,
                          synchronous_read=True, synchronous_write=True,
                          read_ports_per_column=1, write_ports_per_column=1,
                          same_address_read='old data', storage_implementation='inferred synchronous RAM')
        entry = dict(mode=mode, passed=True, script_sha256=sha(script), log_sha256=sha(log),
                     netlist_sha256=sha(netlist), **result)
        report['profiles'].append(entry)
        print(json.dumps(entry), flush=True)
        with gzip.open(str(netlist) + '.gz', 'wb') as stream:
            stream.write(netlist.read_bytes())
        netlist.unlink()
    assert all(sha(source_root / name) == hashes[name] for name in SOURCES)
    report.update(passed=True, source_unchanged_during_checks=True,
                  checker_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
