#!/usr/bin/env python3
"""映射完整预取模块，并分别导出数据端和时钟使能端的寄存器路径。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=root/'build/prefetch_coordinate_measure')
    parser.add_argument('--mapped-directory', type=Path,
                        help='读取已经完成的模块映射，并检查其输入源码散列')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = 'prefetch_coordinate'
    if args.mapped_directory:
        directory = args.mapped_directory.resolve()
    else:
        config = {name: {
            'top': 'conv_im2col_prefetch',
            'options': ['-D', 'SYNTHESIS=1', '-G', 'p_size=16',
                        '-G', 'p_line_bytes=128', '-G', 'p_register_cache_request=1'],
            'sources': [str(root/'rtl/npu/conv'/filename) for filename in (
                'conv_im2col_pkg.sv', 'conv_im2col_frontend_pkg.sv', 'conv_im2col_prefetch.sv')],
            'configuration': '完整预取模块，SIZE=16、128 字节缓存行、寄存缓存请求'}}
        config_path = out/'cases.json'
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n')
        subprocess.run([sys.executable, str(root/'scripts/fpga/open_fpga_synth.py'),
                        '--case-config', str(config_path), '--cases', name,
                        '--out', str(out)], cwd=root, check=True)
        directory = out/name

    manifest = json.loads((directory/'manifest.json').read_text())
    checked_sources = {}
    for filename, expected in manifest['sources_sha256'].items():
        relative = filename[filename.index('rtl/'):] if 'rtl/' in filename else filename
        source = root/relative
        if not source.is_file() or sha256(source) != expected:
            raise RuntimeError(f'Mapping source differs: {source}')
        checked_sources[relative] = expected

    sys.path.insert(0, str(root/'scripts/fpga'))
    import netlist_metrics as metrics
    mapped = directory/'mapped.json'
    content = mapped.read_text() if mapped.exists() else gzip.open(str(mapped)+'.gz', 'rt').read()
    module = json.loads(content)['modules']['conv_im2col_prefetch']
    origins = directory/'pre_lut.il'
    if not origins.exists():
        origins = Path(str(origins)+'.gz')
    for cell, origin in metrics.register_origins(origins).items():
        if cell in module['cells']:
            module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin

    def origin(cell):
        return cell.get('attributes', {}).get('fpga_register_origin', '')

    measured = json.loads((directory/'metrics.json').read_text())
    result = {
        'source_sha256': checked_sources,
        'parameters': {'p_size': 16, 'p_line_bytes': 128, 'p_register_cache_request': 1},
        'resources': measured['resources'],
        'whole_module_longest_cells': measured['paths']['longest_register_path_cells'],
        'whole_module_report': str(directory/'metrics.json'),
        'paths': {},
    }
    views = (
        ('accepted_to_projected', ('accepted_coordinate_q[0]',), ('projected_coordinate_q[0]',)),
        ('all_to_projected', None, ('projected_coordinate_q[0]', 'projected_coordinate_q[1]')),
        ('step_to_projected', ('pf_step_q',), ('projected_coordinate_q[0]',)),
        ('base_to_projected', ('prefetch_wrap_base_q', 'prefetch_base_no_borrow_q'),
         ('projected_coordinate_q[0]',)),
        ('horizontal_carry_input', None, ('prefetch_horizontal_low_carry_q',)),
        ('no_borrow_input', None, ('prefetch_base_no_borrow_q',)),
    )
    for view, starts, ends in views:
        paths = metrics.connected_paths(module, limit=256, group_limit=256,
            root_filter=(lambda n,c,p: any(x in origin(c) for x in starts)) if starts else None,
            sink_filter=lambda n,c,p: any(x in origin(c) for x in ends))
        report = out/(view+'.json')
        report.write_text(json.dumps(paths, indent=2)+'\n')
        ports = {}
        for path in paths['register_to_register_paths']:
            port = path['endpoint']['port']
            ports[port] = max(ports.get(port, 0), path['combinational_cells'])
        result['paths'][view] = {
            'maximum_cells': paths['longest_register_path_cells'] if ports else None,
            'ports': ports, 'report': str(report), 'report_sha256': sha256(report),
            'endpoint_histogram': paths['endpoint_port_maximum_depth_histogram'],
        }
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
