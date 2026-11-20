#!/usr/bin/env python3
"""测量实际行释放计算块及可选完整前端的普通 RTL 映射结果。"""
import argparse
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

from run_formal import ROOT, SOURCE, REFERENCE, DEPENDENCIES, digest, input_declarations, sources
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def measured(body):
    return '''module measured(input logic clk, rst_n,
    input logic [163:0] i_value, input logic [3:0] i_control,
    output logic [63:0] o_value);
  logic [163:0] input_q;
  logic [3:0] control_q;
  logic cfg_valid, cfg_ready;
  logic [1:0] cfg_prepare_phase;
  assign cfg_valid = control_q[0];
  assign cfg_ready = control_q[1];
  assign cfg_prepare_phase = control_q[3:2];
''' + input_declarations('input_q') + '''
  always_ff @(posedge clk) begin
    input_q <= i_value;
    control_q <= i_control;
    o_value <= retirement_result;
  end
''' + body + '\nendmodule\n'


def compress(folder):
    for name in ('elaborated.il', 'pre_lut.il', 'mapped.json'):
        path = folder / name
        if path.exists():
            with path.open('rb') as src, gzip.open(str(path) + '.gz', 'wb', compresslevel=2) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()


def annotate_report(out):
    report = json.loads((out / 'summary.json').read_text())
    for name, result in report['runs'].items():
        if not name.startswith('frontend_'):
            continue
        folder = out / 'native' / name
        with gzip.open(folder / 'mapped.json.gz', 'rt') as stream:
            design = json.load(stream)['modules']['conv_im2col_frontend']
        saved = SimpleNamespace(open=lambda: gzip.open(folder / 'pre_lut.il.gz', 'rt'))
        for cell, origin in register_origins(saved).items():
            if cell in design['cells']:
                design['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin

        def release_endpoint(cell_name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin', '')
            if origin.startswith(('pf0_ref_retire ', 'pf1_retire ')):
                return True
            match = re.fullmatch(r'u_cache\.g_window\.u_window\.work_request \[(\d+)\]', origin)
            return match is not None and 42 <= int(match[1]) < 74

        def coordinate_origin(cell_name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin', '')
            return origin.startswith(('iy ', 'pfa_y ', 'pf0_y ', 'request_y_q '))

        paths = connected_paths(design, limit=10, group_limit=20,
            root_filter=coordinate_origin, sink_filter=release_endpoint)
        if not paths['graph_complete'] or not paths['register_to_register_paths']:
            raise RuntimeError('完整前端的坐标至行释放结果路径未找到')
        result['coordinate_to_release_paths'] = paths
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--frontend', action='store_true', help='同时测量包含缓存和预测器的完整前端')
    parser.add_argument('--frontend-width', type=int, choices=(32, 64), default=32,
                        help='前端内部 AXI 宽度，生产实例使用默认 32 位')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    content, bodies = sources(args.reference_ref)
    report = dict(reference_ref=args.reference_ref, extra_dsp_remapping=False,
                  source_sha256={name: digest(text) for name, text in content.items()},
                  runs={}, changes={})
    cases = {}
    for label in ('reference', 'current'):
        folder = out / 'sources' / label
        folder.mkdir(parents=True, exist_ok=True)
        block = folder / 'measured.sv'
        block.write_text(measured(bodies[label]))
        cases['block_' + label] = dict(top='measured', options=['-j', '1', '-D', 'SYNTHESIS=1'],
            sources=[str(block)], configuration='Two release ports including coefficient preparation; registered I/O')
        if args.frontend:
            rtl = folder / 'conv_im2col_frontend.sv'
            rtl.write_text(content[label])
            parameters = dict(SIZE=16, LANES=4, BUS_WIDTH=args.frontend_width, CACHE_SETS=128, CACHE_WAYS=2,
                              LINE_BYTES=16, CACHE_POLICY=3)
            cases['frontend_' + label] = dict(top='conv_im2col_frontend', parameters=parameters,
                options=['-j', '1', '-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1',
                         *(f'-G{name}={value}' for name, value in parameters.items())],
                sources=[*(str(ROOT / path) for path in DEPENDENCIES
                           if not path.startswith('rtl/common/')), str(rtl)],
                configuration='Frontend with identical cache, predictor and ordinary RTL arithmetic')
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    for name, case in cases.items():
        folder = out / 'native' / name
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--case-config', str(config), '--cases', name, '--out', str(out / 'native')],
            cwd=ROOT, check=True)
        metrics = json.loads((folder / 'metrics.json').read_text())
        paths = metrics['paths']
        if not paths['graph_complete'] or paths['combinational_cycle_nodes']:
            raise RuntimeError('完整无环组合图分析未通过')
        report['runs'][name] = dict(resources=metrics['resources'], parameters=case.get('parameters', {}),
            longest_register_path_cells=paths['longest_register_path_cells'], graph_complete=True,
            longest_path=paths['register_to_register_paths'][0],
            metrics_sha256=digest((folder / 'metrics.json').read_bytes()),
            mapped_sha256=digest((folder / 'mapped.json').read_bytes()),
            stages=json.loads((folder / 'stages.json').read_text()))
        compress(folder)
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for name in ('block', *(['frontend'] if args.frontend else [])):
        before, after = (report['runs'][name + '_' + label] for label in ('reference', 'current'))
        report['changes'][name] = dict(
            resource_delta={key: after['resources'][key] - before['resources'][key] for key in
                ('logic_lut_cells', 'flip_flops', 'dsp48e1', 'carry4', 'ramb18e1',
                 'distributed_ram_lut_sites_nominal')},
            combinational_levels=[before['longest_register_path_cells'], after['longest_register_path_cells']])
    if digest((ROOT / SOURCE).read_bytes()) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during synthesis')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    annotate_report(out)
    print(json.dumps(report['changes']), flush=True)


if __name__ == '__main__':
    main()
