#!/usr/bin/env python3
"""证明 IA 控制输出、有效写入数据和寄存状态的逐周期对应关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import shared_ia_options
SOURCES = [Path('rtl/npu/loaders') / (name + '.sv')
           for name in ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr')]
SOURCES.append(Path('rtl/npu/compute/select_add.sv'))
CASES = {
    'production': dict(SIZE=16, BUS_WIDTH=64, COUNT_WIDTH=29, CACHE_BLOCKS=32,
                       ORDERED_JOB=1, PS_FRAME_COUNT=16,
                       p_dma_source_layout=1, p_shared_write_stage=1),
    'generic': dict(SIZE=16, BUS_WIDTH=32, COUNT_WIDTH=8, CACHE_BLOCKS=4,
                    ORDERED_JOB=0),
    'small': dict(SIZE=16, BUS_WIDTH=32, COUNT_WIDTH=8, CACHE_BLOCKS=2,
                  ORDERED_JOB=1),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_valid_wrapper(root, destination):
    """按实际端口写使能比较数据，同时保留其余全部公开输出。"""
    source = (root / SOURCES[0]).read_text()
    header = source[:source.index(');') + 2].replace(
        'module ia_loader #(', 'module ia_loader_valid #(', 1)
    parameters = re.findall(r'parameter\s+(?:int\s+unsigned|bit|integer)\s+(\w+)\s*=', header)
    body = '\nlogic [127:0] raw_port_data [0:1], raw_shared_data;\n'
    body += 'ia_loader #(\n' + ',\n'.join(f'.{name}({name})' for name in parameters)
    body += ') u_core (.ram_port_wr_data(raw_port_data), .ram_shared_wr_data(raw_shared_data), .*);\n'
    body += "for (genvar port_index=0; port_index<2; port_index++)\n"
    body += "  assign ram_port_wr_data[port_index] = ram_port_wr_en[port_index] ? raw_port_data[port_index] : 128'd0;\n"
    body += "assign ram_shared_wr_data = (|ram_port_wr_en) ? raw_shared_data : 128'd0;\nendmodule\n"
    destination.write_text(header + body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cursor-proof', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=list(CASES))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    paths = {}
    for label, root in roots.items():
        paths[label] = [root / path for path in SOURCES] + sorted(
            path for path in (root / 'rtl/common').iterdir() if path.suffix in ('.v', '.sv'))
        paths[label] += [root / 'rtl/npu/loaders' / helper for helper in
                         ('ia_ordered_coordinate_equal.sv', 'ia_ordered_coordinate_same.sv')
                         if (root / 'rtl/npu/loaders' / helper).is_file()]
    hashes = {label: {str(path.relative_to(roots[label])): digest(path)
                     for path in values} for label, values in paths.items()}
    certificate=json.loads(args.cursor_proof.read_text())
    ctrl=roots['current']/'rtl/npu/loaders/ia_loader_ctrl.sv'
    if not certificate['passed'] or certificate['source_sha256']!=digest(ctrl):
        raise RuntimeError('Cursor relation certificate does not match the source')
    if len([row for row in certificate['runs'] if row['name'].startswith('cursor_w') and row['passed']]) != 9:
        raise RuntimeError('Cursor width coverage')
    text=ctrl.read_text()
    start=text.index('    always_ff',text.index('begin : g_saved_load_boundary'))
    marker='    localparam int p_boundary_groups' if '    localparam int p_boundary_groups' in text else '    assign load_last_equal_o_regular'
    stop=text.index(marker,start)
    normalized=out/'normalized_ctrl.sv'
    normalized.write_text(text[:start]+"    assign cursor_after_q = load_ia_cursor_cnt + LOAD_CNT_W'(1);\n"+text[stop:])
    original_paths={label:list(values)for label,values in paths.items()}
    paths['current']=[normalized if path==ctrl else path for path in paths['current']]
    wrappers = {label: out / (label + '_valid.sv') for label in roots}
    for label, root in roots.items():
        make_valid_wrapper(root, wrappers[label])
    summary = dict(passed=False, inputs_constrained=False,
                   cursor_relation_certificate=str(args.cursor_proof.resolve()),
                   cursor_certificate_sha256=digest(args.cursor_proof),
                   normalized_control_sha256=digest(normalized),
                   proof_method='Unbounded cursor invariant followed by complete-module equivalence using its exact substitution.',
                   source_sha256=hashes, runs=[], write_payload_when_enabled=True,
                   wrapper_sha256={label: digest(path) for label, path in wrappers.items()})
    for name in args.cases:
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GRAM_WORD_ADDR_WIDTH=12'] + [
            '-G' + key + '=' + str(value) for key, value in CASES[name].items()]
        commands = []
        for label in ('reference', 'current'):
            selected_options = shared_ia_options(options, wrappers[label].read_text())
            commands += ['read_slang --top ia_loader_valid ' + shlex.join(selected_options + list(map(str, paths[label] + [wrappers[label]]))),
                'prep -top ia_loader_valid -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename -hide w:*ram_port_wr_data* w:*ram_shared_wr_data* w:raw_port_data w:raw_shared_data w:*cache_slot_rows* w:*u_cache_mgr.slot_rows',
                'rename ia_loader_valid ' + label, 'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3', 'equiv_status -assert']
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = dict(name=name, parameters=CASES[name], passed=run.returncode == 0 and
            'Equivalence successfully proven' in text,
            equivalent_bits=int(match[1]) if match else None,
            script_sha256=digest(script), log_sha256=digest(log))
        summary['runs'].append(row)
        summary['passed'] = all(item['passed'] for item in summary['runs'])
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('IA slot-stage proof did not complete: ' + str(log))
    if hashes != {label: {str(path.relative_to(roots[label])): digest(path)
                         for path in values} for label, values in original_paths.items()}:
        raise RuntimeError('Source changed during IA slot-stage proof')


if __name__ == '__main__':
    main()
