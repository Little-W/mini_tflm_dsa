#!/usr/bin/env python3
"""Run shared INT8 convolution workloads through the DWConv RTL accelerator."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import memory_service


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, logfile, env=None):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=env)
    logfile.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(result.stdout[-3000:])


def convert_int8_stores(raw, destination, expected):
    """Select the native accumulator scaler and compact the output addresses."""
    metadata = json.loads((raw / 'case.json').read_text())
    output_base = metadata['output_base']
    output_bytes = metadata['output_bytes']
    records = []
    stores = 0
    for line in (raw / 'commands.txt').read_text().splitlines():
        if line == 'FENCE':
            records.append(line)
            continue
        funct, rs1, rs2 = (int(value, 0) for value in line.split())
        if funct == 0 and rs1 & 3 == 2:
            stride = rs2 & 0xffffffff
            if stride % 4:
                raise ValueError('INT32 output stride is not a multiple of four')
            rs2 = (0x3d000000 << 32) | (stride // 4)
        elif funct == 3:
            if not output_base <= rs1 < output_base + output_bytes or (rs1 - output_base) % 4:
                raise ValueError('MVOUT does not address the raw output tensor')
            if not rs2 & (1 << 29):
                raise ValueError('Expected a full-width accumulator read')
            rs1 = output_base + (rs1 - output_base) // 4
            rs2 &= ~(1 << 29)
            stores += 1
        records.append(f'{funct} 0x{rs1:016x} 0x{rs2:016x}')
    if not stores:
        raise ValueError('No output stores were recorded')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'memory.bin').write_bytes((raw / 'memory.bin').read_bytes())
    (destination / 'commands.txt').write_text('\n'.join(records) + '\n')
    (destination / 'expected.bin').write_bytes(expected)
    metadata['output_bytes'] //= 4
    metadata['output_format'] = 'int8'
    metadata['hardware_output_scale'] = 0.03125
    metadata['hardware_rounding'] = 'nearest_even'
    metadata['source_raw_commands_sha256'] = digest(raw / 'commands.txt')
    metadata['commands_sha256'] = digest(destination / 'commands.txt')
    metadata['memory_sha256'] = digest(destination / 'memory.bin')
    (destination / 'case.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exporter', type=Path, required=True)
    parser.add_argument('--workloads', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sim', type=Path, required=True)
    parser.add_argument('--build-manifest', type=Path, required=True)
    memory_service.add_arguments(parser)
    parser.add_argument('--tile-height-override', action='append', default=[], metavar='NAME=ROWS',
                        help='Use a specified native-loop tile height for one workload.')
    args = parser.parse_args()
    tile_heights = {}
    for item in args.tile_height_override:
        name, separator, value = item.partition('=')
        if not separator or not value.isdecimal() or int(value) < 1:
            parser.error('--tile-height-override requires NAME=POSITIVE_INTEGER')
        tile_heights[name] = int(value)
    for key in ('exporter', 'workloads', 'output', 'sim', 'build_manifest'):
        setattr(args, key, getattr(args, key).resolve())
    build = json.loads(args.build_manifest.read_text())
    selected_memory = memory_service.configuration(build['memory_service'], args)
    if digest(args.sim) != build['simulator_sha256']:
        raise ValueError('Simulator differs from its build manifest')
    exporter_manifest = args.exporter.parent / 'generator.json'
    exporter_build = None
    if exporter_manifest.is_file():
        exporter_build = json.loads(exporter_manifest.read_text())
        if exporter_build['binary_sha256'] != digest(args.exporter):
            raise ValueError('Exporter differs from its build manifest')
        if exporter_build['vendor']['params_sha256'] != build['params_header_sha256']:
            raise ValueError('Exporter parameters differ from the generated hardware header')
    elif build['configuration']['dma_bus_bits'] == 64:
        raise ValueError('AXI64 tests require the exporter build manifest')
    catalogue = json.loads((args.workloads / 'workloads.json').read_text())
    if set(tile_heights) - {entry['name'] for entry in catalogue['cases']}:
        parser.error('Tile-height override names must appear in the workload catalogue')
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in catalogue['cases']:
        manifest = args.workloads / entry['manifest']
        if digest(manifest) != entry['manifest_sha256']:
            raise ValueError('Shared workload manifest changed')
        source = json.loads(manifest.read_text())
        if source['scale'] != 0.03125 or any(source['zero_points'].values()):
            raise ValueError('Shared operators require zero points 0 and scale 1/32')
        paths = {}
        for name, tensor in source['tensors'].items():
            paths[name] = manifest.parent / tensor['path']
            if paths[name].stat().st_size != tensor['bytes'] or digest(paths[name]) != tensor['sha256']:
                raise ValueError('Shared tensor changed: ' + name)
        case = args.output / entry['name']
        case.mkdir(exist_ok=True)
        channels = source['output_channels']
        multiplier, shift = case / 'multipliers.bin', case / 'shifts.bin'
        multiplier.write_bytes(struct.pack('<i', 1073741824) * channels)
        shift.write_bytes(struct.pack('<i', -4) * channels)
        dimensions = [source[key] for key in ('input_h', 'input_w', 'input_channels',
            'output_h', 'output_w', 'output_channels', 'kernel_h', 'kernel_w',
            'stride_h', 'stride_w', 'pad_top', 'pad_left')]
        raw = case / 'raw'
        command = [str(args.exporter), str(raw), source['operation'], *map(str, dimensions),
                   str(paths['a']), str(paths['weights_npu']), str(paths['bias']),
                   str(multiplier), str(shift), '0', '0', '-128', '127', '0', '0']
        exporter_environment = {}
        if entry['name'] in tile_heights:
            exporter_environment['GEMMINI_TILE_HEIGHT'] = str(tile_heights[entry['name']])
        execute(command, case / 'generation.log', env={**os.environ, **exporter_environment})
        if digest(raw / 'expected.bin') != source['tensors']['c_s32']['sha256']:
            raise ValueError('Exporter INT32 reference differs from the shared accumulator tensor')
        trace = case / 'int8'
        metadata = convert_int8_stores(raw, trace, paths['c_s8'].read_bytes())
        result_path = case / 'result.json'
        simulation = [str(args.sim), str(trace / 'memory.bin'), str(metadata['memory_base']),
                      str(trace / 'commands.txt'), str(metadata['output_base']),
                      str(metadata['output_bytes']), str(trace / 'expected.bin'),
                      str(metadata['timed_start']), str(result_path),
                      *memory_service.simulator_arguments(selected_memory)]
        execute(simulation, case / 'rtl.log')
        result = json.loads(result_path.read_text())
        memory_service.validate_result(result, selected_memory)
        if 'axi_max_beats' in build['configuration'] and (
                result['axi_data_bits'] != build['configuration']['dma_bus_bits'] or
                result['axi_max_beats'] != 256 or result['axi_boundary_bytes'] != 4096):
            raise ValueError('Observed AXI interface differs from the hardware configuration')
        if digest(case / 'result.output.bin') != source['tensors']['c_s8']['sha256']:
            raise ValueError('RTL output differs from the shared INT8 reference')
        if source['operation'] == 'dw' and (not result['loop_depthwise_launches'] or
                                            not result['dwconv_active_cycles']):
            raise ValueError('The specialized DWConv dataflow did not execute')
        if metadata.get('independent_im2col') and (
                not result['independent_im2col_requests'] or
                not result['independent_im2col_responses']):
            raise ValueError('The independent hardware Im2Col dataflow did not execute')
        result.update(name=entry['name'], operation=source['operation'],
                      useful_macs=source['useful_macs'], conv=source['conv'],
                      workload_manifest_sha256=entry['manifest_sha256'],
                      expected_output_sha256=source['tensors']['c_s8']['sha256'],
                      input_tensor_sha256={key: value['sha256'] for key, value in source['tensors'].items()},
                      metadata=metadata, exporter_command=command, simulation_command=simulation,
                      exporter_environment=exporter_environment,
                      build_manifest_sha256=digest(args.build_manifest))
        result_path.write_text(json.dumps(result, indent=2) + '\n')
        results.append(result)
        print(entry['name'], result['cycles'], 'cycles', flush=True)
    (args.output / 'results.json').write_text(json.dumps({
        'passed': all(row['passed'] for row in results), 'cases': results,
        'configuration': build['configuration'],
        'memory_service': selected_memory,
        'exporter_sha256': digest(args.exporter),
        'exporter_build': exporter_build,
        'exporter_manifest_sha256': digest(exporter_manifest) if exporter_build else None,
        'build_manifest_sha256': digest(args.build_manifest)}, indent=2) + '\n')


if __name__ == '__main__':
    main()
