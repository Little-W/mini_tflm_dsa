#!/usr/bin/env python3
"""比较偏置控制器和缓冲区的完整控制、数据以及存储端口。"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ((4, 32, 1, 1), (8, 32, 8, 3), (16, 32, 12, 4),
            (16, 64, 29, 32), (16, 128, 29, 32), (16, 64, 32, 64))
HELPER = Path('rtl/common/parallel_prefix_add.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_text(reference, path):
    return subprocess.check_output(['git', 'show', f'{reference}:{path}'], cwd=ROOT, text=True)


def observe_controller(text, common_registers):
    view = """
  logic [CNT_W-1:0] geometry_count, step_blocks;
  assign geometry_count = state == S_INIT_GEOM ? cfg_m : num_blocks;
  assign step_blocks = state == S_INIT_GEOM ?
      ((cfg_bias_step_blocks == '0) ? count_t'(1) : cfg_bias_step_blocks) : step_blocks_eff;
"""
    text = text.replace('\nendmodule', view + '\nendmodule', 1)
    return observe_controller_state(text, common_registers)


def observe_controller_state(text, common_registers):
    registers = common_registers + ['geometry_count', 'step_blocks']
    position = text.index('\n);', text.index(') ('))
    count_names = {
        'current_block_idx', 'dma_row_offset', 'group_blocks_needed',
        'last_block_elems', 'last_group_start_idx', 'load_block_idx',
        'load_blocks_count', 'load_tail_offset', 'remaining_blocks',
        'geometry_count', 'step_blocks',
    }
    address_names = {'cfg_bias_base', 'dma_base_addr', 'dma_rows_to_read', 'tail_base_addr'}
    flag_names = {
        'active_bank', 'bias_switch_d', 'current_is_last_group', 'dma_start',
        'load_bank', 'load_bias_req', 'load_window_last', 'switch_pending', 'tail_pending',
    }
    widths = {name: '(COUNT_WIDTH < 1 ? 1 : COUNT_WIDTH)' for name in count_names}
    widths.update({name: 'REG_WIDTH' for name in address_names})
    widths.update({name: '1' for name in flag_names})
    widths.update(state='4', dma_burst_len_m1='8')
    if set(registers) != set(widths):
        raise RuntimeError('Controller state width inventory differs from the RTL')
    width = ' + '.join(widths[name] for name in registers)
    text = text[:position] + ',\n    output logic [(' + width + ')-1:0] formal_state' + text[position:]
    view = '\n  assign formal_state = {' + ', '.join(registers) + '};\n'
    return text.replace('\nendmodule', view + '\nendmodule', 1)


def observe_buffer(text, reference):
    port = text.index('\n);', text.index(') ('))
    text = text[:port] + """,
    input logic [63:0] formal_ram_data,
    output logic [31:0] formal_write_addr, formal_read_addr,
    output logic [63:0] formal_write_data,
    output logic [7:0] formal_write_mask,
    output logic formal_write_en, formal_read_en
""" + text[port:]
    start = text.index('  regfile #(')
    end = text.index('\n  );', start) + len('\n  );')
    text = text[:start] + """  assign storage_o_rd_data = formal_ram_data;
  assign formal_write_addr = 32'(storage_i_wr_addr);
  assign formal_read_addr = 32'(storage_i_rd_addr);
  assign formal_write_data = storage_i_wr_data;
  assign formal_write_mask = storage_i_wr_mask;
  assign formal_write_en = storage_i_wr_en;
  assign formal_read_en = storage_i_rd_en;""" + text[end:]
    if reference:
        view = """
  logic [BANK_ADDR_W-1:0] load_row_index_q;
  logic load_row_high_zero_q;
  assign load_row_index_q = BANK_ADDR_W'(load_word_row_q);
  assign load_row_high_zero_q = (load_word_row_q >> BANK_ADDR_W) == '0;
"""
        text = text.replace('\nendmodule', view + '\nendmodule', 1)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='caace947')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path, default=ROOT.parent / 'r20_heavy.lock')
    parser.add_argument('--profiles', nargs='+', default=[':'.join(map(str, row)) for row in PROFILES])
    parser.add_argument('--kind', choices=('all', 'controller', 'buffer'), default='all')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / 'summary.json'
    summary_path.unlink(missing_ok=True)
    snapshots = {}
    hashes = {}
    controller_path = Path('rtl/npu/loaders/bias_loader_ctrl.sv')
    controller_reference = reference_text(args.reference, controller_path)
    controller_current = (ROOT / controller_path).read_text()
    common_registers = sorted(set(re.findall(r'\b(\w+)\s*<=', controller_reference)) &
                              set(re.findall(r'\b(\w+)\s*<=', controller_current)))
    for label in ('reference', 'current'):
        folder = out / 'source' / label
        folder.mkdir(parents=True, exist_ok=True)
        files = {}
        for kind in ('ctrl', 'buffer'):
            relative = Path(f'rtl/npu/loaders/bias_loader_{kind}.sv')
            raw = reference_text(args.reference, relative) if label == 'reference' else (ROOT / relative).read_text()
            original = folder / relative.name
            original.write_text(raw)
            hashes[f'{label}/{relative}'] = digest(original)
            observed = raw
            if kind == 'ctrl':
                observed = observe_controller(raw, common_registers) if label == 'reference' else observe_controller_state(raw, common_registers)
            if kind == 'buffer':
                observed = observe_buffer(raw, label == 'reference')
            target = folder / ('observed_' + relative.name)
            target.write_text(observed)
            files[kind] = target
        helper = folder / HELPER.name
        helper.write_text(reference_text(args.reference, HELPER) if label == 'reference' else (ROOT / HELPER).read_text())
        hashes[f'{label}/{HELPER}'] = digest(helper)
        files['helper'] = helper
        snapshots[label] = files
    rows = []
    for profile in args.profiles:
        size, bus, count, groups = map(int, profile.split(':'))
        variants = [('ctrl', None)] if args.kind == 'controller' else []
        if args.kind == 'all':
            variants.append(('ctrl', None))
        if args.kind != 'controller':
            variants.extend([('buffer', 0), ('buffer', 1)])
        for kind, share in variants:
            name = f'{kind}_s{size}_b{bus}_c{count}_g{groups}' + ('' if share is None else f'_share{share}')
            folder = out / name
            folder.mkdir(exist_ok=True)
            top = 'bias_loader_' + kind
            options = [f'-GSIZE={size}', f'-GBUS_WIDTH={bus}', f'-GCOUNT_WIDTH={count}', f'-GGROUP_BLOCKS_MAX={groups}']
            if share is not None:
                options.append(f'-Gp_share_load_index={share}')
            commands = []
            for label in ('reference', 'current'):
                files = [snapshots[label][kind], snapshots[label]['helper']]
                commands += [f'read_slang --top {top} ' + shlex.join(options + list(map(str, files))),
                             f'prep -top {top} -flatten', 'memory_map', 'async2sync', 'opt_clean',
                             *(['rename -hide w:*'] if kind == 'ctrl' else []),
                             f'rename {top} {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 1']
            if kind == 'buffer':
                commands.append('equiv_simple -seq 2')
            commands += ['opt_clean', 'equiv_induct -seq 4', 'equiv_status -assert']
            script, log, report = folder / 'run.ys', folder / 'formal.log', folder / 'result.json'
            script.write_text('\n'.join(commands) + '\n')
            configuration = dict(kind=kind, SIZE=size, BUS_WIDTH=bus, COUNT_WIDTH=count,
                                 GROUP_BLOCKS_MAX=groups, p_share_load_index=share,
                                 source_sha256=hashes, script_sha256=digest(script))
            if args.resume and report.exists():
                previous = json.loads(report.read_text())
                if all(previous.get(k) == v for k, v in configuration.items()) and previous.get('passed') and log.exists() and previous.get('log_sha256') == digest(log):
                    rows.append(previous)
                    print(json.dumps({'profile': name, 'passed': True, 'reused': True}), flush=True)
                    continue
            report.unlink(missing_ok=True)
            with args.lock_file.open('a+') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                with log.open('w') as stream:
                    result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                                            cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
            text = log.read_text()
            matches = re.findall(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            passed = result.returncode == 0 and 'Equivalence successfully proven' in text
            row = dict(configuration, passed=passed, equivalent_bits=int(matches[-1][0]) if matches else None,
                       log_sha256=digest(log), inputs_constrained=False,
                       memory_return='arbitrary shared 64-bit input' if kind == 'buffer' else None)
            report.write_text(json.dumps(row, indent=2) + '\n')
            rows.append(row)
            print(json.dumps({'profile': name, 'passed': passed, 'equivalent_bits': row['equivalent_bits']}), flush=True)
            if not passed:
                raise RuntimeError(str(log))
    for relative in (HELPER, Path('rtl/npu/loaders/bias_loader_ctrl.sv'), Path('rtl/npu/loaders/bias_loader_buffer.sv')):
        if digest(ROOT / relative) != hashes[f'current/{relative}']:
            raise RuntimeError('验证期间源码发生变化：' + str(relative))
    summary = dict(passed=True, reference=args.reference, source_sha256=hashes, profiles=rows,
                   equivalent_bits=sum(row['equivalent_bits'] for row in rows),
                   inputs_constrained=False, runner_sha256=digest(Path(__file__)))
    summary_path.write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
