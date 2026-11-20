#!/usr/bin/env python3
"""测量相同缓存配置中的预取描述块 RAM，并保存输入与映射结果。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import process_tree_rss

SOURCES = ('rtl/npu/dma/cache/conv_read_cache.sv',
           'rtl/npu/dma/cache/conv_sdp_ram.sv',
           'rtl/npu/conv/conv_axi_span_reader.sv',
           'rtl/common/regfile.v')
PARAMETERS = {'SETS': 128, 'WAYS': 2, 'BUS_WIDTH': 64, 'LINE_BYTES': 16, 'DEMAND_DEPTH': 4}


def run_limited(command, limit):
    peak = 0
    process = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
    try:
        while process.poll() is None:
            peak = max(peak, process_tree_rss(process.pid))
            if peak > limit:
                raise RuntimeError('综合进程树超过指定的驻留内存上限')
            time.sleep(0.2)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)
    return peak


def sha_stream(stream):
    digest = hashlib.sha256()
    while chunk := stream.read(1024*1024):
        digest.update(chunk)
    return digest.hexdigest()


def compress_completed(folder):
    records = []
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.suffix not in ('.il', '.json', '.blif', '.v'):
            continue
        if path.stat().st_size < 1024*1024:
            continue
        with path.open('rb') as stream:
            original = sha_stream(stream)
        target = path.with_suffix(path.suffix + '.gz')
        with path.open('rb') as source, gzip.open(target, 'wb', compresslevel=6) as destination:
            shutil.copyfileobj(source, destination, length=1024*1024)
        with gzip.open(target, 'rb') as stream:
            assert sha_stream(stream) == original
        records.append({'path': str(path), 'sha256': original,
                        'original_bytes': path.stat().st_size, 'compressed_bytes': target.stat().st_size})
        path.unlink()
    return records


def check_retire_port(design, folder):
    """检查实际块 RAM 引脚与原捕获寄存器的时钟和使能连接。"""
    cells, names = design['cells'], design['netnames']
    def wire_bits(*aliases):
        return next(names[alias]['bits'] for alias in aliases if alias in names)
    selected = [(name, cell) for name, cell in cells.items()
                if 'u_prefetch_retire.mem.' in name]
    assert len(selected) == 1
    name, cell = selected[0]
    assert cell['type'] == 'RAMB18E1'
    parameters, ports = cell['parameters'], cell['connections']
    number = lambda key: int(parameters[key], 2)
    assert parameters['RAM_MODE'] == 'SDP'
    assert parameters['WRITE_MODE_A'] == parameters['WRITE_MODE_B'] == 'READ_FIRST'
    assert number('READ_WIDTH_A') == number('WRITE_WIDTH_B') == 36
    assert number('DOA_REG') == number('DOB_REG') == 0
    assert ports['CLKARDCLK'] == ports['CLKBWRCLK'] == names['clk']['bits']
    assert ports['ADDRARDADDR'] == ['0']*5 + names['pf_read_slot']['bits'] + ['0']*6
    assert ports['ADDRBWRADDR'] == ['0']*5 + wire_bits(
        'prefetch_retire_i_wr_addr', 'prefetch_payload_i_wr_addr', 'pf_push_slot') + ['0']*6
    assert ports['WEBWE'] == names['pf_push']['bits'] * 4
    assert ports['WEA'] == ['0', '0'] and ports['ENBWREN'] == ['1']
    assert ports['RSTRAMARSTRAM'] == ports['RSTRAMB'] == ['0']
    output_bits = {bit for port, bits in ports.items()
                   if cell['port_directions'][port] == 'output' for bit in bits}
    assert set(names['pf_retire']['bits']) <= output_bits
    drivers = {bit: (instance, other, port) for instance, other in cells.items()
               for port, bits in other['connections'].items()
               if other['port_directions'][port] == 'output'
               for bit in bits if isinstance(bit, int)}
    capture_bits = names['pf_index']['bits'] + names['pf_index_valid']['bits']
    checked_capture_bits = 0
    for bit in capture_bits:
        if isinstance(bit, int):
            _, capture, _ = drivers[bit]
            assert capture['type'] == 'FDRE'
            assert capture['connections']['CE'] == ports['ENARDEN']
            assert capture['connections']['C'] == ports['CLKARDCLK']
            checked_capture_bits += 1
    assert checked_capture_bits != 0
    return {'passed': True, 'cell': name, 'type': cell['type'],
            'logical_bits': 256, 'logical_rows': 8, 'logical_width': 32,
            'read_mode': 'READ_FIRST', 'read_clock_equals_write_clock': True,
            'read_enable_matches_retained_index_capture': True,
            'retained_capture_bits_checked': checked_capture_bits,
            'extra_output_registers': 0, 'output_hold_when_read_disabled': True,
            'mapped_retire_bits': 32}



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8720e2c7')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--rss-limit-mib', type=int, default=476)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        folder = out / 'sources' / label
        folder.mkdir(parents=True, exist_ok=True)
        paths, hashes[label] = [], {}
        for name in SOURCES:
            content = read_rtl_source(f'{args.reference}:{name}', cwd=ROOT) \
                if label == 'reference' else (ROOT / name).read_bytes()
            target = folder / Path(name).name
            target.write_bytes(content)
            hashes[label][name] = hashlib.sha256(content).hexdigest()
            if name.startswith('rtl/common/'):
                if content != (ROOT / name).read_bytes():
                    raise ValueError('公共存储模块的比较版本不一致')
                paths.append(name)
            else:
                paths.append(str(target))
        cases[label] = {'top': 'conv_windowed_cache', 'sources': paths,
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                       [f'-G{name}={value}' for name, value in PARAMETERS.items()],
            'parameters': PARAMETERS,
            'configuration': '相同容量、端口与周期的 128 组双路缓存'}
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    result = {'reference_ref': args.reference, 'source_sha256': hashes,
              'parameters': PARAMETERS, 'payload_width': 65, 'payload_depth': 8,
              'mapping': {'mode': 'physical-cost', 'small_lut_area_cost': 1,
                          'max_lut_inputs': 6, 'wire_delay_ps': 500, 'delay_target_ps': 6667},
              'results': {}, 'compressed_files': []}
    if args.prepare_only:
        (out / 'inputs.json').write_text(json.dumps(result, indent=2) + '\n')
        print(config)
        return
    for label in cases:
        native_peak = run_limited([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--case-config', str(config), '--cases', label, '--through', 'pre_lut',
            '--out', str(out / 'native')], args.rss_limit_mib*1024*1024)
        source, mapped = out / 'native' / label, out / 'mapped' / label
        mapped_peak = run_limited([sys.executable, str(ROOT / 'scripts/fpga/remap_fpga_luts.py'),
            '--source', str(source), '--out', str(mapped), '--mode', 'physical-cost',
            '--small-lut-area-cost', '1', '--max-lut-inputs', '6',
            '--wire-delay-ps', '500', '--delay-target-ps', '6667'], args.rss_limit_mib*1024*1024)
        metrics = json.loads((mapped / 'metrics.json').read_text())
        design = json.loads((mapped / 'mapped.json').read_text())['modules']['conv_windowed_cache']
        payload_cells = {name: cell for name, cell in design['cells'].items()
                         if any(part in name for part in ('u_prefetch_payload.mem.',
                             'u_prefetch_retire.mem.', 'u_prefetch_index.mem.'))}
        native_stages = json.loads((source / 'stages.json').read_text())
        mapped_summary = json.loads((mapped / 'summary.json').read_text())
        recorded_peaks = [stage['peak_process_tree_rss_bytes'] for stage in native_stages.values()]
        recorded_peaks.append(mapped_summary['mapping_stage']['peak_process_tree_rss_bytes'])
        result['results'][label] = {'resources': metrics['resources'],
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'peak_process_tree_rss_bytes': max(native_peak, mapped_peak, *recorded_peaks),
            'payload_cells': payload_cells,
            'native_stages': native_stages,
            'mapped_summary': mapped_summary}
        if label == 'current':
            result['retire_bram_port_check'] = check_retire_port(design, mapped)
        del design
        result['compressed_files'] += compress_completed(source)
        result['compressed_files'] += compress_completed(mapped)
        (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
        print(label, metrics['resources'], flush=True)
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != value
           for name, value in hashes['current'].items()):
        raise RuntimeError('测量期间 RTL 内容变化')
    result['passed'] = True
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
