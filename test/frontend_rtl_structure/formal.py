#!/usr/bin/env python3
"""证明卷积前端、读取通道和权重模块的公开输出与对应状态。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
COMMON = [
    'rtl/npu/conv/conv_im2col_pkg.sv',
    'rtl/npu/dma/cache/conv_read_cache.sv',
    'rtl/npu/dma/cache/conv_sdp_ram.sv',
    'rtl/npu/dma/cache/conv_next_use_predictor.sv',
    'rtl/npu/conv/conv_axi_span_reader.sv',
    'rtl/common/onehot_check.sv',
    'rtl/common/add_equal.sv',
    'rtl/common/add3_equal.sv',
    'rtl/common/regfile.v',
]
CASES = {
    'cache128': ('conv_windowed_cache', ['rtl/npu/dma/cache/conv_read_cache.sv',
        'rtl/npu/dma/cache/conv_sdp_ram.sv', 'rtl/npu/conv/conv_axi_span_reader.sv',
        'rtl/common/regfile.v'], {'SETS': 128, 'WAYS': 2, 'BUS_WIDTH': 64}),
    'mux32': ('conv_axi_read_mux', ['rtl/npu/conv/conv_axi_read_mux.sv'], {'DATA_W': 32}),
    'mux64': ('conv_axi_read_mux', ['rtl/npu/conv/conv_axi_read_mux.sv'], {'DATA_W': 64}),
    'linear32': ('axi_linear_block_dma', ['rtl/npu/dma/axi_linear_block_dma.sv',
        'rtl/common/regfile.v', 'rtl/common/add_equal.sv'], {'BUS_WIDTH': 32}),
    'linear64': ('axi_linear_block_dma', ['rtl/npu/dma/axi_linear_block_dma.sv',
        'rtl/common/regfile.v', 'rtl/common/add_equal.sv'], {'BUS_WIDTH': 64}),
    'kernel64': ('kernel_loader', ['rtl/npu/loaders/kernel_loader.sv',
        'rtl/npu/loaders/kernel_loader_ctrl.sv', 'rtl/npu/loaders/kernel_loader_buffer.sv',
        'rtl/common/regfile.v', 'rtl/common/add_equal.sv', 'rtl/common/add3_equal.sv'],
        {'SIZE': 16, 'DATA_WIDTH': 16, 'BUS_WIDTH': 64}),
}
CASES['kernel64_c29'] = ('kernel_loader', CASES['kernel64'][1],
    {**CASES['kernel64'][2], 'COUNT_WIDTH': 29})
for line_bytes, ways, bus_width in ((8, 1, 32), (256, 2, 64)):
    CASES[f'cache_line{line_bytes}'] = ('conv_windowed_cache', CASES['cache128'][1],
        {'SETS': 2, 'WAYS': ways, 'BUS_WIDTH': bus_width, 'LINE_BYTES': line_bytes})
for context_depth in (1, 2, 3):
    CASES[f'linear64_c{context_depth}'] = ('axi_linear_block_dma',
        ['rtl/npu/dma/axi_linear_block_dma.sv', 'rtl/common/regfile.v',
         'rtl/common/add_equal.sv'], {'BUS_WIDTH': 64, 'RD_CONTEXT_DEPTH': context_depth})
CASES['linear64_s64'] = ('axi_linear_block_dma',
    ['rtl/npu/dma/axi_linear_block_dma.sv', 'rtl/common/regfile.v',
     'rtl/common/add_equal.sv'], {'BUS_WIDTH': 64, 'SIZE': 64, 'CACHE_BLOCKS': 64})
for depth in (2, 3, 4, 7, 8):
    CASES[f'window_d{depth}'] = ('conv_window_queue',
        ['rtl/npu/dma/conv_window_queue.sv', 'rtl/common/regfile.v'], {'DEPTH': depth})
for lanes in (1, 2, 3, 4):
    CASES[f'frontend_l{lanes}'] = ('conv_im2col_frontend',
        [COMMON[0], 'rtl/npu/conv/conv_im2col_frontend.sv', *COMMON[1:]],
        {'SIZE': 16, 'LANES': lanes, 'BUS_WIDTH': 64, 'CACHE_SETS': 8, 'CACHE_POLICY': 3})


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=list(CASES))
    parser.add_argument('--retimed-dma-base', action='store_true',
        help='逐字比较拆分后的描述符基地址存储，公开输出及完整行地址仍参加证明')
    parser.add_argument('--retimed-kernel-buffer', action='store_true',
        help='同步读取时独立处理内部 RAM 读端口，全部公开输出和其余对应状态参加等价证明')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    library_text = library.read_text()
    models = []
    for name in ('LUT1', 'LUT2', 'LUT3', 'LUT4', 'LUT5', 'LUT6', 'LUT6_2', 'MUXF7', 'MUXF8', 'DSP48E1'):
        block = re.search(r'^module ' + name + r'\b.*?^endmodule', library_text, re.M | re.S)[0]
        models.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', block, flags=re.S))
    model = out / 'primitives.sv'
    model.write_text('\n'.join(models) + '\n')
    report = {'reference': subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT,
        text=True).strip(), 'fpga': True, 'inputs_constrained': False,
        'official_model_sha256': sha(library.read_bytes()), 'cases': []}
    for name in args.cases:
        top, sources, parameters = CASES[name]
        folder = out / name
        folder.mkdir(exist_ok=True)
        commands = []
        hashes = {}
        for label in ('reference', 'current'):
            copied = []
            hashes[label] = {}
            for source in sources:
                content = read_rtl_source(args.reference + ':' + source, cwd=ROOT) \
                    if label == 'reference' else (ROOT / source).read_bytes()
                target = folder / label / source
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                copied.append(target)
                hashes[label][source] = sha(content)
            options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
            commands += ['read_slang --top ' + top + ' -D SYNTHESIS=1 -D XILINX_FPGA=1 '
                '-D YOSYS=1 -D VERIFIC=1 ' + options + ' ' +
                ' '.join(shlex.quote(str(path)) for path in [*copied, model]),
                'prep -top ' + top + ' -flatten', 'memory_map', 'async2sync', 'opt_clean']
            if args.retimed_dma_base and top == 'axi_linear_block_dma' and label == 'reference':
                text = (folder / label / sources[0]).read_text()
                if 'u_context_base' not in text:
                    # 将原存储字的基地址字段命名为独立存储字，逐位证明相同写入与保持行为。
                    reg_width = parameters.get('REG_WIDTH', 32)
                    size = parameters.get('SIZE', 16)
                    cache_blocks = parameters.get('CACHE_BLOCKS', 4)
                    row_width = max(1, size.bit_length())
                    slot_width = max(1, (cache_blocks-1).bit_length())
                    word_width = 4*reg_width + row_width + slot_width + 10
                    commands.append('cd ' + top)
                    for address in range(max(1, parameters.get('RD_CONTEXT_DEPTH', 4))):
                        base_name = f'u_context_base.mem[{address}]'
                        head_name = f'u_context_storage.mem[{address}]'
                        full_name = f'proof_context_word[{address}]'
                        commands += [f'rename {head_name} {full_name}',
                            f'add -wire {head_name} {word_width-reg_width}',
                            f'connect -set {head_name} {full_name}[{word_width-reg_width-1}:0]',
                            f'add -wire {base_name} {reg_width}',
                            f'connect -set {base_name} {full_name}[{word_width-1}:{word_width-reg_width}]']
                    commands.append('cd ..')
            if top == 'conv_window_queue' and 'g_descriptor' in (folder / label / sources[0]).read_text():
                # 按原有字段及地址逐字匹配存储内容，全部公开读数据仍参加比较。
                commands.append('cd ' + top)
                for field_index, field in enumerate(('p0', 'q0', 'cols')):
                    for address in range(parameters['DEPTH']):
                        commands.append(f'rename g_descriptor[{field_index}].u_value.mem[{address}] '
                                        f'{field}[{address}]')
                commands.append('cd ..')
            commands += ['rename ' + top + ' ' + label, 'design -stash ' + label]
        unmatched = []
        make_options = ''
        if args.retimed_kernel_buffer and top == 'kernel_loader':
            # 读端口的寄存边界随同步 RAM 调整，权重输出和存储内容仍完整比较。
            unmatched = ['u_buf.column_i_rd_en', 'u_buf.column_o_rd_data']
            for column in range(parameters['SIZE']):
                for port in ('i_rd_en', 'o_rd_data'):
                    unmatched.append(f'u_buf.g_column_ram[{column}].u_column.{port}')
            names = folder / 'retimed_internal_ports.txt'
            names.write_text('\n'.join(unmatched) + '\n')
            make_options = '-blacklist ' + shlex.quote(str(names)) + ' '
        commands += ['design -copy-from reference reference', 'design -copy-from current current',
            'equiv_make ' + make_options + 'reference current equivalent', 'hierarchy -top equivalent',
            'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
            'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        content = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', content)
        passed = result.returncode == 0 and 'Equivalence successfully proven' in content
        entry = {'name': name, 'top': top, 'parameters': parameters, 'passed': passed,
            'equivalent_bits': int(match[1]) if match else None,
            'source_sha256': hashes, 'log_sha256': sha(log.read_bytes()),
            'unmatched_internal_ports': unmatched}
        report['cases'].append(entry)
        report['passed'] = all(case['passed'] for case in report['cases'])
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({key: value for key, value in entry.items() if key != 'source_sha256'}), flush=True)
        if not passed:
            print(content[-6000:])
            raise SystemExit(1)
        for source in sources:
            if sha((ROOT / source).read_bytes()) != hashes['current'][source]:
                raise RuntimeError('验证期间源码发生变化: ' + source)
        with gzip.open(str(log) + '.gz', 'wb') as stream:
            stream.write(log.read_bytes())
        log.unlink()


if __name__ == '__main__':
    main()
