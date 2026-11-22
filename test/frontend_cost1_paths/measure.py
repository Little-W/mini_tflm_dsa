#!/usr/bin/env python3
"""使用相同六输入 LUT 面积成本测量预测器与读取保护器。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from rtl_reference import read_rtl_source
from netlist_metrics import connected_paths, register_origins


def product_bit_paths(design):
    """以乘积输出各半字为分析起点，资源统计仍使用原始网表。"""
    results = {}
    name = 'analysis_product_boundary'
    if name in design['cells']:
        raise ValueError('路径分析起点名称重复')
    for part, low, high in (('low', 0, 16), ('high', 16, 32)):
        bits = design['netnames']['mul_x_s0']['bits'][low:high] + \
               design['netnames']['mul_y_s0']['bits'][low:high]
        design['cells'][name] = {'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': 'product_' + part + '_boundary'},
            'connections': {'D': ['0'], 'Q': bits},
            'port_directions': {'D': 'input', 'Q': 'output'}}
        paths = connected_paths(design, limit=1, group_limit=0,
            root_filter=lambda cell_name, cell, port: cell_name == name,
            sink_filter=lambda cell_name, cell, port:
                cell.get('attributes', {}).get('fpga_register_origin') in ('coordinate_good_s1', 'coordinate_good[1]', 'coordinate_good [1]'))
        if not paths['graph_complete']:
            raise RuntimeError('乘积输出位到坐标有效结果的路径未完整分析')
        results[part] = paths
    del design['cells'][name]
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--modules', nargs='+', choices=('predictor', 'guard'),
                        default=['predictor', 'guard'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {
        'predictor': ['rtl/npu/conv/conv_im2col_pkg.sv',
            'rtl/npu/dma/cache/conv_next_use_predictor.sv', 'rtl/common/onehot_check.sv'],
        'guard': ['rtl/npu/conv/conv_axi_read_guard.sv'],
    }
    tops = {'predictor': 'conv_next_use_predictor', 'guard': 'conv_axi_read_guard'}
    cases, hashes = {}, {}
    for kind, names in sources.items():
        if kind not in args.modules:
            continue
        for label in ('reference', 'current'):
            name = kind + '_' + label
            folder = out / 'sources' / name
            folder.mkdir(parents=True, exist_ok=True)
            paths = []
            hashes[name] = {}
            for source in names:
                content = read_rtl_source(args.reference + ':' + source, cwd=ROOT) \
                    if label == 'reference' else (ROOT / source).read_bytes()
                target = folder / Path(source).name
                target.write_bytes(content)
                # 公共综合入口统一读取公共模块，核对其内容后采用仓库内路径。
                if source.startswith('rtl/common/'):
                    if content != (ROOT / source).read_bytes():
                        raise ValueError('公共模块版本不同，需要独立展开后比较: ' + source)
                    paths.append(source)
                else:
                    paths.append(str(target))
                hashes[name][source] = hashlib.sha256(content).hexdigest()
            options = ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1']
            if kind == 'guard':
                options += ['-GADDR_W=32', '-GDATA_W=64', '-GSPLIT_GEMM_4K=1', '-GREAD_OUTSTANDING=4']
            cases[name] = {'top': tops[kind], 'sources': paths, 'options': options,
                'configuration': '普通算术映射，固定六输入 LUT 成本及原语引脚延迟'}
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
        '--out', str(out / 'native'), '--case-config', str(config), '--cases', *cases,
        '--through', 'pre_lut'], cwd=ROOT, check=True)
    report = {'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference],
        cwd=ROOT, text=True).strip(), 'source_sha256': hashes,
        'max_lut_inputs': 6, 'small_lut_area_cost': 1, 'wire_delay_ps': 500,
        'delay_target_ps': 6667, 'wide_alu_dsp_budget': None, 'results': {}}
    for name, case in cases.items():
        source, folder = out / 'native' / name, out / 'mapped' / name
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/remap_fpga_luts.py'),
            '--source', str(source), '--out', str(folder), '--mode', 'physical-cost',
            '--max-lut-inputs', '6', '--small-lut-area-cost', '1', '--wire-delay-ps', '500',
            '--delay-target-ps', '6667'], cwd=ROOT, check=True)
        metrics = json.loads((folder / 'metrics.json').read_text())
        result = {'resources': metrics['resources'],
                  'longest_register_path_cells': metrics['paths']['longest_register_path_cells']}
        if name.startswith('predictor'):
            design = json.loads((folder / 'mapped.json').read_text())['modules'][case['top']]
            for cell, origin in register_origins(source / 'pre_lut.il').items():
                if cell in design['cells']:
                    design['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
            paths = connected_paths(design, limit=1, group_limit=0,
                root_filter=lambda cell_name, cell, port: cell['type'] == 'DSP48E1',
                sink_filter=lambda cell_name, cell, port:
                    cell.get('attributes', {}).get('fpga_register_origin') in ('coordinate_good_s1', 'coordinate_good[1]', 'coordinate_good [1]'))
            if not paths['graph_complete']:
                raise RuntimeError('坐标计算路径未完整分析')
            result['dsp_to_coordinate_good'] = paths
            result['product_output_bit_paths'] = product_bit_paths(design)
        else:
            spec = importlib.util.spec_from_file_location('guard_paths', ROOT / 'test/conv_guard/measure_paths.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result['guard_port_paths'] = module.measure(folder)
        report['results'][name] = result
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'name': name, 'lut': result['resources']['logic_lut_cells'],
            'carry4': result['resources']['carry4'],
            'depth': result['longest_register_path_cells']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
