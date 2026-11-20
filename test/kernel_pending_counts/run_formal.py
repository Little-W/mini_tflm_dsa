#!/usr/bin/env python3
"""证明权重加载差值计数、真实缓存状态和 DMA 完成归属。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
GROUPS = ('buffer', 'kernel', 'control', 'comparisons', 'linear', 'image')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cut_outputs(module, names):
    """只扩大算术结果的可取值，保留对应的实际控制逻辑。"""
    vectors = [net['bits'] for net in module['netnames'].values()]
    vectors += [port['bits'] for port in module['ports'].values()]
    vectors += [bits for cell in module['cells'].values() for bits in cell['connections'].values()]
    next_bit = max(bit for bits in vectors for bit in bits if isinstance(bit, int)) + 1
    for name in names:
        bits = module['netnames'][name]['bits']
        assert len(bits) == 1 and isinstance(bits[0], int), name
        bit = bits[0]
        drivers = []
        for cell_name, cell in module['cells'].items():
            for port, connection in cell['connections'].items():
                if cell['port_directions'][port] == 'output' and bit in connection:
                    drivers.append((cell_name, port))
                    cell['connections'][port] = [next_bit if value == bit else value
                                                  for value in connection]
        assert len(drivers) == 1, (name, drivers)
        module['netnames']['expanded_result_' + name.replace('.', '_')] = {
            'hide_name': 0, 'bits': [next_bit], 'attributes': {}}
        next_bit += 1
        free_name = 'free_' + name.replace('.', '_')
        module['ports'][free_name] = {'direction': 'input', 'bits': bits}
        module['netnames'][free_name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
    driven_bits = {}
    for name, cell in module['cells'].items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] != 'output':
                continue
            for bit in bits:
                if isinstance(bit, int):
                    assert bit not in driven_bits, (bit, driven_bits.get(bit), name, port)
                    driven_bits[bit] = (name, port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8d7dc595')
    parser.add_argument('--groups', nargs='+', choices=GROUPS, default=GROUPS)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'reference'
    reference.mkdir(exist_ok=True)
    tracked = list(HERE.iterdir()) + [ROOT / 'rtl/npu/loaders' / name for name in
        ('kernel_loader_ctrl.sv', 'kernel_loader.sv', 'kernel_loader_buffer.sv')]
    tracked += [ROOT / path for path in (
        'rtl/npu/dma/axi_linear_block_dma.sv', 'rtl/npu/dma/axi_dual_block_dma.sv',
        'rtl/common/regfile.v', 'rtl/common/add_equal.sv', 'rtl/common/add3_equal.sv',
        'test/monitors/kernel_loader_observer.sv', 'scripts/fpga/open_fpga_synth.py')]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in tracked if path.is_file()}
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    for name in ('kernel_loader_ctrl.sv', 'kernel_loader.sv', 'kernel_loader_buffer.sv'):
        (reference / name).write_bytes(read_rtl_source(f'{revision}:rtl/npu/loaders/{name}', cwd=ROOT))
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'xilinx_models.sv'
    primitives = ('LUT1', 'LUT6', 'LUT6_2', 'MUXF7', 'MUXF8', 'DSP48E1')
    model.write_text('\n\n'.join(re.sub(r'\bspecify\b.*?\bendspecify\b', '',
        re.search(r'^module ' + name + r'\b.*?^endmodule', library.read_text(), re.M | re.S).group(),
        flags=re.S) for name in primitives) + '\n')
    report = {'reference_revision': revision, 'source_sha256': hashes,
              'reference_sha256': {path.name: digest(path) for path in reference.iterdir()},
              'primitive_library_sha256': digest(library), 'results': {},
              'parameters': {'SIZE': 16, 'COUNT_WIDTH': 29, 'cumulative_count_width': 87,
                             'BUS_WIDTH': 64, 'DMA_SIZE': 64, 'DMA_CACHE_BLOCKS': 64,
                             'DMA_contexts': 4, 'DMA_tag_width': 3},
              'production_checks': 'test/monitors/kernel_loader_observer.sv'}

    def run(name, script, proven=False):
        path = out / (name + '.ys')
        path.write_text(script)
        log = out / (name + '.log')
        start = time.monotonic()
        with log.open('w') as output:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(path)], cwd=ROOT, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        if result.returncode or (proven and 'SUCCESS!' not in text):
            raise RuntimeError(f'Formal check did not complete successfully: {log}')
        if proven:
            report['results'][name] = {'passed': True, 'elapsed_seconds': time.monotonic() - start,
                                      'log_sha256': digest(log), 'script_sha256': digest(path)}
            (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')

    formal_tail = 'memory_map\nasync2sync\nopt -full\n'
    if 'buffer' in args.groups:
        run('buffer', f'''read_slang --top buffer_pending -GSIZE=16 rtl/npu/loaders/kernel_loader_buffer.sv rtl/common/regfile.v {HERE / 'buffer_pending.sv'}
prep -top buffer_pending -flatten
{formal_tail}sat -verify -tempinduct -seq 4 -maxsteps 12 -timeout 45 -set-init-zero -set rst_n 1 -set-at 1 rst_n 0 -prove bounds 1 -prove relation 1
''', True)
    if 'kernel' in args.groups:
        complete = out / 'kernel_complete.json'
        run('kernel_elaborate', f'''read_slang -D VERIFIC=1 -D YOSYS=1 -D SYNTHESIS=1 --top kernel_pending -GCOUNT_WIDTH=29 {HERE / 'kernel_pending.sv'} {reference / 'kernel_loader.sv'} {reference / 'kernel_loader_ctrl.sv'} {reference / 'kernel_loader_buffer.sv'} rtl/common/regfile.v rtl/common/add_equal.sv rtl/common/add3_equal.sv {model}
prep -top kernel_pending -flatten
write_json {complete}
''')
        design = json.loads(complete.read_text())
        module = design['modules']['kernel_pending']
        cuts = ['dut.comparison_equal', 'dut.u_ctrl.last_col_in_group',
                'dut.u_ctrl.last_tile_row', 'dut.u_ctrl.last_l2_group', 'dut.u_ctrl.last_repeat',
                'dut.u_ctrl.load_limit_o_ge', 'dut.u_ctrl.sent_count_covers_loads']
        cut_outputs(module, cuts)
        module['ports'] = {name: port for name, port in module['ports'].items()
                           if port['direction'] == 'input' or name in ('relation', 'bounds', 'event_relation')}
        abstracted = out / 'kernel_control.json'
        abstracted.write_text(json.dumps(design))
        run('kernel', f'''read_json {abstracted}
hierarchy -top kernel_pending
opt_clean
{formal_tail}sat -verify -tempinduct -seq 2 -maxsteps 8 -timeout 45 -set-init-zero -set requested_rst_n 1 -prove relation 1 -prove bounds 1 -prove event_relation 1
''', True)
        report['results']['kernel']['arithmetic_outputs_expanded_to_free_inputs'] = cuts
        report['results']['kernel']['environment'] = [
            'A DMA response retires a previously accepted slot at most once.',
            'A new loader command begins with no previous demanded block pending.',
            'Command mode remains stable until cache flush.',
            'Cache flush removes previous DMA ownership; production flush occurs after completion.']
    if 'control' in args.groups:
        subprocess.run([sys.executable, str(HERE / 'control_builder.py'), str(out)],
                       cwd=ROOT, check=True)
        script = (out / 'control.ys').read_text()
        run('control', script, True)
    if 'comparisons' in args.groups:
        run('comparisons', f'''read_slang --top compare_pending {HERE / 'compare_pending.sv'}
prep -top compare_pending -flatten
sat -verify -prove equivalent 1 -show-inputs -show-outputs
''', True)
    if 'linear' in args.groups:
        source = (ROOT / 'rtl/npu/dma/axi_linear_block_dma.sv').read_text()
        header = source[source.index('module axi_linear_block_dma'):].split(');', 1)[0]
        header = header.replace('module axi_linear_block_dma', 'module linear_ownership')
        header = header.replace('input logic rst_n,', 'input logic requested_rst_n,')
        wrapper = out / 'linear_ownership.sv'
        wrapper.write_text(header.rstrip() + ',\n output logic relation\n);\n' +
                           (HERE / 'linear_owner_body.sv.inc').read_text())
        complete = out / 'linear_complete.json'
        run('linear_elaborate', f'''read_slang -D SYNTHESIS=1 -D YOSYS=1 -D VERIFIC=1 --top linear_ownership -GBUS_WIDTH=64 -GSIZE=64 -GCACHE_BLOCKS=64 {wrapper} rtl/npu/dma/axi_linear_block_dma.sv rtl/common/regfile.v rtl/common/add_equal.sv {model}
prep -top linear_ownership -flatten
write_json {complete}
''')
        design = json.loads(complete.read_text())
        module = design['modules']['linear_ownership']
        cuts = ['dut.rd_rsp_last_without_cross', 'dut.rd_rsp_last_with_cross',
                'dut.rsp_row_equal_o_equal', 'dut.rd_issue_last_ar', 'dut.rd_rsp_cross']
        cut_outputs(module, cuts)
        module['ports'] = {name: port for name, port in module['ports'].items()
                           if port['direction'] == 'input' or name == 'relation'}
        abstracted = out / 'linear_control.json'
        abstracted.write_text(json.dumps(design))
        run('linear', f'''read_json {abstracted}
hierarchy -top linear_ownership
opt_clean
{formal_tail}sat -verify -tempinduct -seq 2 -maxsteps 8 -timeout 45 -set-init-zero -prove relation 1
''', True)
        report['results']['linear']['arithmetic_outputs_expanded_to_free_inputs'] = cuts
    if 'image' in args.groups:
        source = (ROOT / 'rtl/npu/dma/axi_dual_block_dma.sv').read_text()
        begin = source.index('    assign rd_busy =')
        accept = source[begin:source.index('    assign rd_response_tag', begin)]
        begin = source.index('    always_ff @(posedge clk or negedge rst_n) begin')
        sequential = source[begin:source.index('    // The old engine', begin)]
        wrapper = out / 'image_ownership.sv'
        wrapper.write_text((HERE / 'image_owner_template.sv.inc').read_text().replace(
            '@@CONTROL@@', accept + sequential))
        run('image', f'''read_slang --top image_ownership {wrapper}
prep -top image_ownership -flatten
{formal_tail}sat -verify -set-assumes -tempinduct -seq 2 -maxsteps 4 -timeout 45 -set-init-zero -prove relation 1
''', True)
        report['results']['image']['environment'] = 'conv_active implies !linear_finish; checked on the actual NPU instance.'
        report['results']['image']['actual_source_excerpts_sha256'] = hashlib.sha256(
            (accept + sequential).encode()).hexdigest()
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError('Source files changed during formal verification')
    report['passed'] = all(result['passed'] for result in report['results'].values())
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'checks': sorted(report['results'])}))


if __name__ == '__main__':
    main()
