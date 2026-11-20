#!/usr/bin/env python3
"""保留完整 IA 控制器及 NPU 仲裁连接，测量 SoC 参数下的寄存器路径。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
import open_fpga_synth as flow
import remap_fpga_luts as remap
from netlist_metrics import connected_paths, register_origins, resources

CHANGED = ('rtl/npu/loaders/ia_loader.sv', 'rtl/npu/loaders/ia_loader_ctrl.sv')
BOUNDARIES = ('axi_dual_block_dma', 'ia_loader_cache_mgr', 'kernel_loader', 'bias_loader',
              'vector_engine', 'compute_core', 'vec_requant', 'vec_s8_to_fifo', 'vec_s16_to_fifo',
              'oa_writer', 'ia_ps_shared_ram', 'ia_ps_channel_ram')
QUERIES = {
    'reuse_to_grant': (r'u_ia_loader(?:\.u_ctrl)?\.cfg_ia_reuse_num \[', r'u_block_dma_arbiter\.rd_grant_client \['),
    'reuse_to_arbiter': (r'u_ia_loader(?:\.u_ctrl)?\.cfg_ia_reuse_num \[', r'u_block_dma_arbiter\.'),
    'cursor_to_grant': (r'u_ia_loader\.u_ctrl\.load_ia_cursor \[', r'u_block_dma_arbiter\.rd_grant_client \['),
    'coordinate_to_grant': (r'u_ia_loader\.u_ctrl\.(request_p0|load_cursor_p0|tile_col_idx|next_l1_idx) \[', r'u_block_dma_arbiter\.rd_grant_client \['),
    'slot_to_client_counts': (r'u_ia_loader\.u_ctrl\.tl_slot_id_r \[', r'u_block_dma_arbiter\.(rd_client_inflight\[|g_client_inflight\[\d+\]\.count_q)'),
    'ia_to_arbiter': (r'u_ia_loader\.', r'u_block_dma_arbiter\.'),
    'all_to_grant': (r'.', r'u_block_dma_arbiter\.rd_grant_client \['),
    'all_to_client_counts': (r'.', r'u_block_dma_arbiter\.(rd_client_inflight\[|g_client_inflight\[\d+\]\.count_q)'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(folder, name, script):
    path = folder / (name + '.ys')
    path.write_text(script)
    with (folder / (name + '.log')).open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(path)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def measure(mapped, pre_lut):
    module = json.loads(mapped.read_text())['modules']['npu_top']
    usage = resources(module['cells'])
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    removed = []
    for name, cell in list(module['cells'].items()):
        if cell['type'] == '$scopeinfo' or cell['type'].startswith(BOUNDARIES):
            removed.append({'cell': name, 'type': cell['type']})
            del module['cells'][name]
    paths = {}
    for name, (start, end) in QUERIES.items():
        first, last = re.compile(start), re.compile(end)
        paths[name] = connected_paths(module, limit=5, group_limit=4,
            root_filter=lambda n, c, p: bool(first.search(c.get('attributes', {}).get('fpga_register_origin', ''))),
            sink_filter=lambda n, c, p: bool(last.search(c.get('attributes', {}).get('fpga_register_origin', ''))))
        if not paths[name]['graph_complete']:
            raise RuntimeError('IA request graph is incomplete: ' + name)
    return {'resources': usage, 'paths': paths, 'interface_boundaries': removed,
            'mapped_sha256': digest(mapped), 'pre_lut_sha256': digest(pre_lut)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='3c8cafeb')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--current-root', type=Path, default=ROOT)
    parser.add_argument('--cases', nargs='+', choices=('reference', 'current'), default=('reference', 'current'))
    parser.add_argument('--lock-file', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx'
    case = dict(flow.CASES['npu_top'])
    case['options'] = [*case['options'], '-GADDR_WIDTH=32']
    with args.lock_file.open('a') as lock:
        print('Waiting for synthesis lock: ' + str(args.lock_file), flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label in args.cases:
            folder = out / label
            folder.mkdir(exist_ok=True)
            source_paths, hashes = [], {}
            for name in case['sources']:
                data = ((args.current_root / name).read_bytes() if label == 'current' and name in CHANGED else
                        read_rtl_source(args.reference + ':' + name, cwd=ROOT))
                path = folder / 'sources' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                source_paths.append(path)
                hashes[name] = hashlib.sha256(data).hexdigest()
            primitive_options, primitive_info = flow.primitive_models(folder,
                [str(path) for path in source_paths], library)
            manifest = {'reference_revision': args.reference, 'changed_files': CHANGED,
                        'source_sha256': hashes, 'options': case['options'],
                        'primitive_models': primitive_info, 'boundaries': BOUNDARIES,
                        'controller_output_analysis_boundaries': False, 'address_width': 32,
                        'count_width': 29, 'full_ia_controller': True}
            (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            pre_lut = folder / 'pre_lut.il'
            commands = ('read_slang --keep-hierarchy --top npu_top -I ' +
                shlex.quote(str(ROOT / 'include')) + ' -I ' + shlex.quote(str(ROOT / 'rtl/npu/ps_compact')) +
                ' ' + primitive_options + ' ' + ' '.join(map(shlex.quote, case['options'])) + ' ' +
                ' '.join(shlex.quote(str(path)) for path in source_paths) + '\n' +
                'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n' +
                'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n' +
                'blackbox ' + ' '.join(name + '*' for name in BOUNDARIES) + '\n' +
                'hierarchy -check -top npu_top\n' +
                'synth_xilinx -top npu_top -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n' +
                'write_rtlil ' + shlex.quote(str(pre_lut)) + '\n')
            run(folder, '02_pre_lut', commands)
            cost_library = folder / 'physical.lut'
            raw_library = folder / 'native.lut'
            run(folder, '01_lut_library', 'read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                'add -mod lut_library_top\nabc9_ops -prep_lut 0\nabc9_ops -write_lut ' +
                shlex.quote(str(raw_library)) + '\n')
            library_info = remap.physical_cost_library(raw_library, cost_library, 8)
            run(folder, '03_map_lut', remap.mapping_commands('npu_top', pre_lut, folder,
                'physical-cost', 6667, 300, cost_library))
            verification = remap.verify_mapping('physical-cost', folder, os.environ.copy())
            report = measure(folder / 'mapped.json', pre_lut)
            report.update(manifest=manifest, manifest_sha256=digest(folder / 'manifest.json'),
                          lut_library=library_info, functional_verification=verification)
            (folder / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'case': label, 'logic_luts': report['resources']['logic_lut_cells'],
                'paths': {name: value['longest_register_path_cells'] for name, value in report['paths'].items()}}), flush=True)
    summaries = {label: json.loads((out / label / 'summary.json').read_text())
                 for label in ('reference', 'current') if (out / label / 'summary.json').exists()}
    (out / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')


if __name__ == '__main__':
    main()
