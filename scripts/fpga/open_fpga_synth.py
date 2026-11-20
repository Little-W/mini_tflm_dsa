#!/usr/bin/env python3
"""Measure mapped Xilinx 7-series module resources with open-source Yosys."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

from netlist_metrics import analyze, register_origins
from lut_dependencies import lut_output_dependencies

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_DEFINES = ['SYNTHESIS=1', 'XILINX_FPGA=1', 'XILINX_CLK_WIZ_IP=1',
                      'GEMPACT_PS_COMPRESS=1', 'GEMMORA_PS_POOL_BYTES=49152',
                      'GEMMORA_PS_FORCE_RAW=1']
PRODUCTION_CONFIG = {
    'PCR_ENGINE': '1', 'SIZE': '16', 'NPU_AXI_DATA_WIDTH': '64',
    'IM2COL_CACHE_BYTES': '4096', 'SHARED_BANK_BYTES': '8192', 'SHARED_BANK_COUNT': '7',
    'IA_CACHE_BLOCKS': '4', 'PS_FRAME_COUNT': '16', 'AXI_READ_OUTSTANDING': '4',
    'PS_POOL_BYTES': '49152', 'PS_FORCE_RAW': '1',
}
_production_options = [item for value in PRODUCTION_DEFINES for item in ('-D', value)]
CASES = {
    'array': {
        'top': 'ws_systolic_array',
        'options': ['-D', 'SYNTHESIS=1', '-GSIZE=16', '-GDATA_IN_WIDTH=16', '-GWEIGHT_WIDTH=16'],
        'sources': ['rtl/npu/compute/ws_systolic_cell.sv', 'rtl/npu/compute/ws_systolic_array.sv'],
        'configuration': '16 x 16, signed 16-bit inputs and weights; identity weight-enable buffers',
    },
    'shared_ram': {
        'top': 'ia_ps_shared_ram',
        'options': ['-GBANK_BYTES=8192', '-GTOTAL_BYTES=57344'],
        'sources': ['rtl/npu/buffers/ia_ps_shared_ram.sv'],
        'configuration': '7 banks, 8192 bytes per bank',
    },
    'vector_writeback': {
        'top': 'vector_writeback',
        'options': ['-GTILE=16', '-GBUS_WIDTH=64'],
        'sources': ['rtl/npu/conv/vector_writeback.sv'],
        'configuration': '16 result lanes, 64-bit bus',
    },
    'conv_cache_ram': {
        'top': 'conv_sdp_ram',
        'options': ['-GDEPTH=256', '-GWRITE_WIDTH=64'],
        'sources': ['rtl/npu/dma/cache/conv_sdp_ram.sv'],
        'configuration': '256 32-bit words, 64-bit byte-enabled writes',
    },
    'vector_engine': {
        'top': 'vector_engine',
        'options': ['-D', 'SYNTHESIS=1', '-GTILE=16', '-GBUS_WIDTH=64', '-GPE_COUNT=8'],
        'sources': ['rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/vector_engine_pkg.sv',
                    'rtl/npu/conv/vector_config_check.sv', 'rtl/npu/conv/vector_writeback.sv',
                    'rtl/npu/conv/vector_round_shift.sv', 'rtl/npu/conv/vector_scalar_multiplier.sv',
                    'rtl/npu/conv/vector_pe.sv', 'rtl/npu/conv/vector_softmax.sv',
                    'rtl/npu/conv/vector_quant_params.sv',
                    'rtl/npu/conv/vector_engine.sv'],
        'configuration': '16 result lanes, 8 vector processing elements, 64-bit bus',
    },
}
DEFAULT_CASES = tuple(CASES)
_packages = ['rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/vector_engine_pkg.sv']
_common_sources = [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'rtl/common').rglob('*'))
                   if path.suffix in ('.v', '.sv')]
_npu_sources = _packages + [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'rtl/npu').rglob('*'))
                            if path.suffix in ('.v', '.sv') and str(path.relative_to(ROOT)) not in _packages]
_npu_sources += _common_sources
CASES['npu_top'] = {
    'top': 'npu_top',
    'options': _production_options + ['-GSIZE=16', '-GBUS_WIDTH=64', '-GSHARED_BANK_BYTES=8192',
                                    '-GSHARED_BANK_COUNT=7', '-GIA_CACHE_BLOCKS=4', '-GPS_FRAME_COUNT=16',
                                    '-GIM2COL_CACHE_BYTES=4096', '-GVECTOR_PE_COUNT=8',
                                    '-GAXI_READ_OUTSTANDING=4', '-GAXI_WRITE_OUTSTANDING=4'],
    'sources': _npu_sources,
    'configuration': '16 x 16 NPU, 64-bit bus, 7 shared banks of 8 KiB',
    'production_configuration': True,
}
_soc_parameters = {
    'SIZE': 16, 'BUS_WIDTH': 64, 'IA_CACHE_BLOCKS': 4, 'IM2COL_CACHE_BYTES': 4096,
    'SHARED_BANK_BYTES': 8192, 'SHARED_BANK_COUNT': 7, 'PS_FRAME_COUNT': 16,
    'AXI_READ_OUTSTANDING': 4, 'AXI_WRITE_OUTSTANDING': 4,
    'ENABLE_VECTOR_ENGINE': 1, 'VECTOR_PE_COUNT': 8,
    'CPU_MEM_DP': 65536, 'CPU_MEM_WORD_WIDTH': 64, 'CPU_MEM_INIT_EN': 0,
    'CPU_ENABLE_ICACHE': 0, 'CPU_ENABLE_MUL': 1, 'CPU_ENABLE_DIV': 1,
    'NPU_ENABLE_IS_MODE': 1, 'NPU_ENABLE_PER_CHANNEL': 1,
    'NPU_ENABLE_CLOCK_GATING': 1, 'NPU_AXI_TIMING_BUFFER': 1,
    'CPU_AXI_WRITE_TIMING_BUFFER': 1, 'BYPASS_RAM_PINGPONG': 0,
    'RAM_WRITE_TIMING_BUFFER': 1,
}
_soc_sources = _npu_sources + [str(path.relative_to(ROOT))
    for folder in ('rtl/axi_top', 'rtl/soc') for path in sorted((ROOT / folder).rglob('*'))
    if path.suffix in ('.v', '.sv')]
_soc_sources += ['rtl/soc_top.sv', 'picorv32/picorv32.v', 'picorv32/picosoc/simpleuart.v']
CASES['soc_top'] = {
    'top': 'soc_top',
    'options': _production_options + [f'-G{name}={value}' for name, value in _soc_parameters.items()],
    'sources': _soc_sources,
    'configuration': '16 x 16 NPU, 64-bit bus, 7 shared banks of 8 KiB; PicoRV32 and 256 KiB CPU RAM',
    'parameters': _soc_parameters,
    'production_configuration': True,
}
for _case in CASES.values():
    _case['sources'] = list(dict.fromkeys(_case['sources'] + _common_sources))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def production_configuration():
    path = ROOT / 'config/npu_fpga.mk'
    values = dict(re.findall(r'^([A-Z][A-Z0-9_]*)\s*\??=\s*([^#\n]+)', path.read_text(), re.MULTILINE))
    values = {key: value.strip() for key, value in values.items()}
    mismatch = {key: {'expected': value, 'configured': values.get(key)}
                for key, value in PRODUCTION_CONFIG.items() if values.get(key) != value}
    if mismatch:
        raise RuntimeError('The production synthesis configuration differs from config/npu_fpga.mk: ' + json.dumps(mismatch))
    return {'path': 'config/npu_fpga.mk', 'sha256': digest(path), 'values': values,
            'defines': PRODUCTION_DEFINES}


def production_structure_commands(case, folder):
    top = case['top']
    selected = [f'{top}/w:*g_shared_ia_ps.*u_ram.*',
                f'{top}/w:*u_ps_buffer.g_compressed.u_store.*']
    commands = [f'select -assert-any {pattern}' for pattern in selected]
    if top == 'soc_top':
        commands += [f'select -assert-count 1 {top}/t:BUFGCE',
                     f'select -assert-count 1 {top}/m:u_axi_sim_ram.mem_r']
        selected += [f'{top}/t:BUFGCE', f'{top}/m:u_axi_sim_ram.mem_r']
    commands += [f'select -write {shlex.quote(str(folder / "elaboration_structure.txt"))} ' + ' '.join(selected),
                 'select -clear']
    return '\n'.join(commands) + '\n'


def primitive_models(folder, sources, library_directory):
    """Copy required functional models from Yosys and retain their primitive parameters."""
    source_text = '\n'.join((ROOT / name).read_text() for name in sources)
    blocks = []
    selected = []
    hashes = {}
    for filename in ('cells_sim.v', 'cells_xtra.v'):
        library = library_directory / filename
        hashes[filename] = digest(library)
        for match in re.finditer(r'^module\s+(\w+)\b.*?^endmodule', library.read_text(), re.MULTILINE | re.DOTALL):
            name = match.group(1)
            if not re.search(r'\b' + re.escape(name) + r'\s*(?:#\s*\(|[A-Za-z_]\w*\s*\()', source_text):
                continue
            # Slang checks specify syntax even for uninstantiated library cells.
            # Synthesis uses the functional body; device timing comes from P&R.
            blocks.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', match.group(0), flags=re.DOTALL))
            selected.append(name)
    model = folder / 'xilinx_primitives.sv'
    model.write_text('\n\n'.join(blocks) + '\n')
    options = ' '.join('--blackboxed-module ' + name for name in selected)
    if selected:
        options += ' -v ' + shlex.quote(str(model))
    return options, {'library_sha256': hashes, 'primitives': selected, 'model_sha256': digest(model)}

def logic_depth(cells):
    """统计 LUT、进位、选择及异步存储读取的逐位组合深度。"""
    logic = {n: c for n, c in cells.items()
             if re.fullmatch(r'LUT(?:[1-6]|6_2)|CARRY4|MUXF[78]|INV|SRL16E|SRLC32E|RAM(?:32M|64M|32X1D|64X1D|128X1S|256X1S)', c['type'])}
    drivers = {}
    for name, cell in logic.items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for index, bit in enumerate(bits):
                    if isinstance(bit, int):
                        drivers[bit] = (name, port, index)
    children = collections.defaultdict(set)
    parents = {}
    for node in drivers.values():
        name, output_port, output_index = node
        cell = logic[name]
        inputs = []
        selected_lut_inputs = lut_output_dependencies(cell, output_port)
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] != 'input':
                continue
            if selected_lut_inputs is not None:
                continue
            if cell['type'].startswith(('RAM', 'SRL')) and not re.fullmatch(r'ADDR[A-D]|A|A[0-9]+|DPRA[0-9]+', port):
                continue
            if cell['type'] == 'CARRY4' and port in ('S', 'DI'):
                stop = output_index + (port == 'S' or output_port == 'CO')
                bits = bits[:stop]
            inputs.extend(bits)
        if selected_lut_inputs is not None:
            inputs = [bit for _, _, bit in selected_lut_inputs]
        parents[node] = {drivers[bit] for bit in inputs if isinstance(bit, int) and bit in drivers}
        for parent in parents[node]:
            children[parent].add(node)
    degree = {node: len(items) for node, items in parents.items()}
    depth = {node: 1 for node in parents}
    predecessor = {}
    ready = collections.deque(node for node, count in degree.items() if count == 0)
    visited = 0
    while ready:
        name = ready.popleft()
        visited += 1
        for child in sorted(children[name]):
            if depth[name] + 1 > depth[child]:
                depth[child] = depth[name] + 1
                predecessor[child] = name
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
    if visited != len(parents):
        raise RuntimeError('Combinational cycle in mapped design')
    if not depth:
        return []
    last = max(depth, key=lambda name: (depth[name], name))
    path = []
    while True:
        path.append({'cell': last[0], 'type': logic[last[0]]['type']})
        if last not in predecessor:
            break
        last = predecessor[last]
    return list(reversed(path))

def worker(script):
    from pyosys import libyosys as yosys
    yosys.run_pass('script ' + shlex.quote(str(script)))


def process_tree_rss(pid):
    """Measure resident bytes of a synthesis worker and its current descendants."""
    total = 0
    pending = [pid]
    while pending:
        current = pending.pop()
        try:
            status = Path(f'/proc/{current}/status').read_text()
            match = re.search(r'^VmRSS:\s+(\d+)\s+kB$', status, re.MULTILINE)
            if match:
                total += int(match.group(1)) * 1024
            children = Path(f'/proc/{current}/task/{current}/children').read_text().split()
            pending.extend(map(int, children))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return total


def run_stage(script, log_path, env, command=None):
    """Run one saved script and record elapsed time and sampled process memory."""
    start = time.monotonic()
    peak = 0
    with log_path.open('w') as log:
        if command is None:
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(script)]
        process = subprocess.Popen(command,
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            peak = max(peak, process_tree_rss(process.pid))
            time.sleep(0.2)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, process.args)
    return {'elapsed_seconds': round(time.monotonic() - start, 2),
            'peak_process_tree_rss_bytes': peak, 'memory_sample_interval_seconds': 0.2,
            'script': script.name, 'log': log_path.name}


def import_elaboration(source, folder, manifest, script):
    """Reuse an elaborated design only when every source and production input agrees."""
    source_manifest = json.loads((source / 'manifest.json').read_text())
    comparable = lambda value: {key: item for key, item in value.items() if key != 'wide_alu_mapping'}
    if comparable(source_manifest) != comparable(manifest):
        raise RuntimeError('Imported elaboration has different sources, configuration, or primitive models')
    source_stages = json.loads((source / 'stages.json').read_text())
    source_stage = source_stages['01_elaborate']
    source_output = source / 'elaborated.il'
    if source_stage['output_sha256'] != digest(source_output):
        raise RuntimeError('Imported elaboration differs from its saved stage digest')
    output = folder / 'elaborated.il'
    shutil.copyfile(source_output, output)
    if digest(output) != source_stage['output_sha256']:
        raise RuntimeError('Imported elaboration changed while it was copied')
    if (source / 'elaboration_structure.txt').exists():
        shutil.copyfile(source / 'elaboration_structure.txt', folder / 'elaboration_structure.txt')
    log_path = folder / '01_elaborate.log'
    log_path.write_text('Reused validated elaboration from ' + str(source) + '\n')
    return {'elapsed_seconds': 0.0, 'peak_process_tree_rss_bytes': 0,
            'script': script.name, 'log': log_path.name,
            'imported_from': str(source), 'source_manifest_sha256': digest(source / 'manifest.json'),
            'source_stage': source_stage}


def import_pre_alu(source, folder, manifest, script):
    """输入摘要与综合步骤相同时复用算术映射之前的网表。"""
    source_manifest = json.loads((source / 'manifest.json').read_text())
    comparable = lambda value: {key: item for key, item in value.items() if key != 'wide_alu_mapping'}
    if comparable(source_manifest) != comparable(manifest):
        raise RuntimeError('Imported arithmetic checkpoint has different inputs')
    source_stage = json.loads((source / 'stages.json').read_text())['02a_pre_alu']
    source_script = source / '02a_pre_alu.ys'
    if digest(source_script) != source_stage['script_sha256']:
        raise RuntimeError('Imported arithmetic script differs from its saved digest')
    old_commands = source_script.read_text().replace(str(source), '${CASE_DIRECTORY}')
    new_commands = script.read_text().replace(str(folder), '${CASE_DIRECTORY}')
    if old_commands != new_commands:
        raise RuntimeError('Imported arithmetic checkpoint uses different synthesis commands')
    source_output = source / 'pre_alu.json'
    if digest(source_output) != source_stage['output_sha256']:
        raise RuntimeError('Imported arithmetic checkpoint differs from its saved digest')
    output = folder / 'pre_alu.json'
    shutil.copyfile(source_output, output)
    if digest(output) != source_stage['output_sha256']:
        raise RuntimeError('Imported arithmetic checkpoint changed while copied')
    log_path = folder / '02a_pre_alu.log'
    log_path.write_text('Reused validated arithmetic checkpoint from ' + str(source) + '\n')
    return {'elapsed_seconds': 0.0, 'peak_process_tree_rss_bytes': 0,
            'script': script.name, 'log': log_path.name,
            'imported_from': str(source), 'source_manifest_sha256': digest(source / 'manifest.json'),
            'source_stage': source_stage}

def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--cases', nargs='+', default=list(DEFAULT_CASES), help='Case names: ' + ', '.join(CASES))
    parser.add_argument('--source-root', type=Path, default=ROOT, help='Repository or worktree containing RTL')
    parser.add_argument('--case-config', type=Path, help='JSON mapping additional case names to top/options/sources/configuration')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--lock-file', type=Path, help='Serialize synthesis jobs using this advisory lock')
    parser.add_argument('--resume', action='store_true', help='Reuse completed stages with identical inputs and scripts')
    parser.add_argument('--through', choices=('elaborate', 'pre_lut', 'mapped'), default='mapped',
                        help='Stop after saving the requested synthesis checkpoint')
    parser.add_argument('--wide-alu-dsp-budget', type=int,
                        help='Map independent wide arithmetic cells to DSPs within this total DSP budget')
    parser.add_argument('--wide-alu-dsp-reserve', type=int, default=0,
                        help='DSP capacity reserved beyond the mapped design')
    parser.add_argument('--wide-alu-minimum-width', type=int, default=24)
    parser.add_argument('--wide-alu-maximum-chain', type=int, choices=(1, 2), default=1)
    parser.add_argument('--reuse-elaboration-from', type=Path,
                        help='Case directory containing a validated elaborated.il with identical inputs')
    parser.add_argument('--reuse-pre-alu-from', type=Path,
                        help='Case directory containing validated elaboration and pre_alu.json with identical inputs')
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if args.reuse_pre_alu_from and (args.reuse_elaboration_from or args.wide_alu_dsp_budget is None):
        parser.error('--reuse-pre-alu-from requires a DSP budget and replaces --reuse-elaboration-from')
    if args.wide_alu_dsp_budget is not None and (args.wide_alu_dsp_budget < 0 or args.wide_alu_dsp_reserve < 0
                                               or not 1 <= args.wide_alu_minimum_width <= 48):
        parser.error('Invalid wide arithmetic DSP budget, reserve, or minimum width')
    ROOT = args.source_root.resolve()
    if args.out is None:
        args.out = ROOT / 'build/open_fpga_synth'
    common = [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'rtl/common').rglob('*'))
              if path.suffix in ('.v', '.sv')]
    npu_sources = _packages + [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'rtl/npu').rglob('*'))
        if path.suffix in ('.v', '.sv') and str(path.relative_to(ROOT)) not in _packages] + common
    CASES['npu_top']['sources'] = npu_sources
    CASES['soc_top']['sources'] = npu_sources + [str(path.relative_to(ROOT))
        for folder in ('rtl/axi_top', 'rtl/soc') for path in sorted((ROOT / folder).rglob('*'))
        if path.suffix in ('.v', '.sv')] + ['rtl/soc_top.sv', 'picorv32/picorv32.v', 'picorv32/picosoc/simpleuart.v']
    vector_parameters = 'rtl/npu/conv/vector_quant_params.sv'
    if (ROOT / vector_parameters).exists():
        CASES['vector_engine']['sources'].append(vector_parameters)
    if args.case_config:
        CASES.update(json.loads(args.case_config.read_text()))
    for case in CASES.values():
        case['sources'] = list(dict.fromkeys([name for name in case['sources'] if not name.startswith('rtl/common/')] + common))
    unknown_cases = set(args.cases) - CASES.keys()
    if unknown_cases:
        parser.error('Unknown cases: ' + ', '.join(sorted(unknown_cases)))
    lock_handle = None
    if args.lock_file:
        import fcntl
        args.lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = args.lock_file.open('a')
        print(f'Waiting for synthesis lock: {args.lock_file}', flush=True)
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
    from pyosys import libyosys as yosys
    import pyosys
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = {'tool': yosys.yosys_maybe_version(), 'family': 'xc7', 'part': 'xc7a200tfbg484-3',
              'clock_period_ns': 6.667, 'cases': {},
              'method': 'synth_xilinx -noiopad -noclkbuf -flatten; mapped combinational cell graph',
              'timing': 'Clock period is the requested implementation constraint. Structural cell depth does not supply device or routing delay. metrics.json records connected register paths and primitive register settings.'}
    env = os.environ.copy()
    env['PATH'] = str(Path(pyosys.__file__).parent) + os.pathsep + env.get('PATH', '')
    for name in args.cases:
        case = CASES[name]
        folder = out / name
        folder.mkdir(exist_ok=True)
        source_hash = {f: digest(ROOT / f) for f in case['sources']}
        mapped = folder / 'mapped.json'
        mapped_verilog = folder / 'mapped.v'
        opts = ' '.join(shlex.quote(x) for x in case['options'])
        sources = ' '.join(shlex.quote(str(ROOT / x)) for x in case['sources'])
        primitive_options, primitive_manifest = primitive_models(
            folder, case['sources'], Path(pyosys.__file__).parent / 'share/xilinx')
        top = case['top']
        build_configuration = production_configuration() if case.get('production_configuration') else None
        structure_commands = production_structure_commands(case, folder) if build_configuration else ''
        start = time.monotonic()
        elaborated = folder / 'elaborated.il'
        pre_lut = folder / 'pre_lut.il'
        synth_command = f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten'
        stage_commands = {
            '01_elaborate': f'read_slang --top {top} -I {shlex.quote(str(ROOT / "include"))} '
                            f'-I {shlex.quote(str(ROOT / "rtl/npu/ps_compact"))} '
                            f'{primitive_options} {opts} {sources}\n'
                            'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
                            'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
                            f'hierarchy -check -top {top}\n'
                            f'{structure_commands}'
                            f'write_rtlil {shlex.quote(str(elaborated))}\n',
            '02_pre_lut': f'read_rtlil {shlex.quote(str(elaborated))}\n'
                          f'{synth_command} -run begin:map_luts\n'
                          f'write_rtlil {shlex.quote(str(pre_lut))}\n',
            '03_map_lut': f'read_rtlil {shlex.quote(str(pre_lut))}\n'
                          'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
                          'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
                          f'{synth_command} -run map_luts:\n'
                          'check -assert\nstat -tech xilinx\n'
                          f'write_json {shlex.quote(str(mapped))}\n'
                          'clkbufmap -buf BUFG O:I\n'
                          'iopadmap -bits -inpad IBUF O:I -outpad OBUF I:O\n'
                          'clean\ncheck -assert\nblackbox =A:whitebox\n'
                          f'write_verilog -noattr -noexpr {shlex.quote(str(mapped_verilog))}\n',
        }
        stage_outputs = {'01_elaborate': elaborated, '02_pre_lut': pre_lut, '03_map_lut': mapped}
        external_commands = {}
        wide_alu_configuration = None
        if args.wide_alu_dsp_budget is not None:
            helper_directory = Path(__file__).resolve().parent
            mapper = helper_directory / 'map_wide_alu.py'
            mapping = helper_directory / 'techmap/wide_alu_dsp.sv'
            pre_alu = folder / 'pre_alu.json'
            mapped_alu = folder / 'mapped_alu.json'
            mapping_report = folder / 'wide_alu_mapping.json'
            command = [sys.executable, str(mapper), '--input', str(pre_alu), '--output', str(mapped_alu),
                       '--report', str(mapping_report), '--top', top, '--budget', str(args.wide_alu_dsp_budget),
                       '--reserve', str(args.wide_alu_dsp_reserve),
                       '--minimum-width', str(args.wide_alu_minimum_width)]
            if args.wide_alu_maximum_chain != 1:
                command += ['--maximum-chain', str(args.wide_alu_maximum_chain)]
            external_commands['02b_map_alu'] = command
            stage_commands = {
                '01_elaborate': stage_commands['01_elaborate'],
                '02a_pre_alu': f'read_rtlil {shlex.quote(str(elaborated))}\n'
                               f'{synth_command} -run begin:fine\n'
                               f'select {top}\nwrite_json -selected {shlex.quote(str(pre_alu))}\nselect -clear\n',
                '02b_map_alu': json.dumps(command, indent=2) + '\n',
                '02_pre_lut': f'read_rtlil {shlex.quote(str(mapped_alu.with_suffix(".autoidx.il")))}\n'
                              f'read_json {shlex.quote(str(mapped_alu))}\n'
                              'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
                              'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
                              'verilog_defaults -push\nverilog_defaults -add -sv\n'
                              f'techmap -map {shlex.quote(str(mapping))}\nverilog_defaults -pop\nopt_clean\n'
                              f'{synth_command} -run fine:map_luts\n'
                              f'write_rtlil {shlex.quote(str(pre_lut))}\n',
                '03_map_lut': stage_commands['03_map_lut'],
            }
            stage_outputs.update({'02a_pre_alu': pre_alu, '02b_map_alu': mapped_alu})
            wide_alu_configuration = {
                'total_dsp_budget': args.wide_alu_dsp_budget, 'reserved_dsp_cells': args.wide_alu_dsp_reserve,
                'minimum_width': args.wide_alu_minimum_width, 'maximum_width': 48,
                'mapper_sha256': digest(mapper), 'techmap_sha256': digest(mapping),
                'lut_dependencies_sha256': digest(helper_directory / 'lut_dependencies.py'),
            }
            if args.wide_alu_maximum_chain != 1:
                wide_alu_configuration['maximum_selected_combinational_dsps'] = args.wide_alu_maximum_chain
        stages = {}
        manifest = {'top': top, 'configuration': case['configuration'],
                    'parameters': case.get('parameters', {}), 'sources_sha256': source_hash,
                    'options': case['options'],
                    'build_configuration': build_configuration,
                    'primitive_models': primitive_manifest,
                    'part': result['part'], 'clock_period_ns': result['clock_period_ns']}
        if wide_alu_configuration:
            manifest['wide_alu_mapping'] = wide_alu_configuration
        previous_stages = {}
        if args.resume and (folder / 'manifest.json').exists():
            previous_manifest = json.loads((folder / 'manifest.json').read_text())
            if previous_manifest != manifest:
                raise RuntimeError(f'Resume inputs differ from the saved manifest: {name}')
            if (folder / 'stages.json').exists():
                previous_stages = json.loads((folder / 'stages.json').read_text())
        (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        reused_inputs = True
        limit = {'elaborate': 1, 'pre_lut': len(stage_commands) - 1, 'mapped': len(stage_commands)}[args.through]
        for stage, commands in list(stage_commands.items())[:limit]:
            suffix = '.command.json' if stage in external_commands else '.ys'
            script = folder / (stage + suffix)
            script.write_text(commands)
            output = stage_outputs[stage]
            previous = previous_stages.get(stage, {})
            reusable = (reused_inputs and previous.get('script_sha256') == digest(script)
                        and output.exists() and previous.get('output_sha256') == digest(output))
            if stage == '02b_map_alu':
                counter_file = output.with_suffix('.autoidx.il')
                reusable = (reusable and counter_file.exists() and
                            previous.get('automatic_name_counter_sha256') == digest(counter_file))
            if stage == '03_map_lut':
                reusable = (reusable and mapped_verilog.exists() and
                            previous.get('mapped_verilog_sha256') == digest(mapped_verilog))
            if reusable:
                stages[stage] = previous
            else:
                reused_inputs = False
                import_source = args.reuse_pre_alu_from or args.reuse_elaboration_from
                if stage == '01_elaborate' and import_source:
                    stages[stage] = import_elaboration(import_source.resolve(), folder, manifest, script)
                elif stage == '02a_pre_alu' and args.reuse_pre_alu_from:
                    stages[stage] = import_pre_alu(args.reuse_pre_alu_from.resolve(), folder, manifest, script)
                else:
                    stages[stage] = run_stage(script, folder / f'{stage}.log', env, external_commands.get(stage))
                stages[stage]['script_sha256'] = digest(script)
                stages[stage]['output_sha256'] = digest(output)
                if stage == '02b_map_alu':
                    stages[stage]['automatic_name_counter_sha256'] = digest(output.with_suffix('.autoidx.il'))
                if stage == '03_map_lut':
                    stages[stage]['mapped_verilog_sha256'] = digest(mapped_verilog)
            (folder / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')
            print(name, stage, json.dumps(stages[stage]), flush=True)
        if source_hash != {f: digest(ROOT / f) for f in case['sources']}:
            raise RuntimeError('Sources changed during synthesis: ' + name)
        if build_configuration and build_configuration != production_configuration():
            raise RuntimeError('Production configuration changed during synthesis: ' + name)
        if args.through != 'mapped':
            continue
        design = json.loads(mapped.read_text())
        for cell_name, origin_name in register_origins(pre_lut).items():
            if cell_name in design['modules'][top]['cells']:
                design['modules'][top]['cells'][cell_name].setdefault('attributes', {})['fpga_register_origin'] = origin_name
        counts = collections.Counter(c['type'] for c in design['modules'][top]['cells'].values())
        if args.wide_alu_dsp_budget is not None and counts['DSP48E1'] + args.wide_alu_dsp_reserve > args.wide_alu_dsp_budget:
            raise RuntimeError('Mapped DSP count exceeds the configured capacity')
        unmapped = {kind: count for kind, count in counts.items() if kind.startswith('$')}
        if unmapped:
            raise RuntimeError(f'Unmapped cells remain in {name}: {unmapped}')
        path = logic_depth(design['modules'][top]['cells'])
        metrics = analyze(design['modules'][top])
        (folder / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
        result['cases'][name] = {
            'top': top, 'configuration': case['configuration'], 'sources_sha256': source_hash,
            'parameters': case.get('parameters', {}), 'stages': stages,
            'options': case['options'],
            'build_configuration': build_configuration,
            'elapsed_seconds': round(time.monotonic() - start, 2),
            'lut_cells': metrics['resources']['logic_lut_cells'],
            'flip_flops': sum(v for k, v in counts.items() if k.startswith(('FDCE', 'FDPE', 'FDRE', 'FDSE'))),
            'ramb36': counts['RAMB36E1'], 'ramb18': counts['RAMB18E1'], 'dsp': counts['DSP48E1'],
            'carry4': counts['CARRY4'], 'longest_combinational_path_cells': len(path),
            'longest_combinational_path': path,
            'cell_counts': dict(sorted(counts.items())),
            'resources': metrics['resources'],
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'register_path_requirement': metrics['register_path_requirement'],
            'mapped_verilog': {'file': str(mapped_verilog), 'sha256': digest(mapped_verilog),
                               'port_cells': 'IBUF/OBUF', 'clock_buffers': 'BUFG'},
        }
        if wide_alu_configuration:
            result['cases'][name]['wide_alu_mapping'] = json.loads(mapping_report.read_text())
        (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
        print(name, json.dumps({k: result['cases'][name][k] for k in
              ('lut_cells', 'flip_flops', 'ramb36', 'ramb18', 'dsp', 'longest_combinational_path_cells')}), flush=True)

if __name__ == '__main__':
    main()
