#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import memory_service

parser = argparse.ArgumentParser()
parser.add_argument('--sim', type=Path, required=True)
parser.add_argument('--traces', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--params-header', type=Path, required=True)
parser.add_argument('--build-manifest', type=Path, required=True)
parser.add_argument('--case', action='append')
memory_service.add_arguments(parser)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
names = args.case or [p.parent.name for p in sorted(args.traces.glob('*/metadata.json'))]
results = []
header_hash = hashlib.sha256(args.params_header.read_bytes()).hexdigest()
build_bytes = args.build_manifest.read_bytes()
build = json.loads(build_bytes)
build_hash = hashlib.sha256(build_bytes).hexdigest()
selected_memory = memory_service.configuration(build['memory_service'], args)
if build['params_header_sha256'] != header_hash:
    raise SystemExit('Build manifest and hardware parameter header differ')
if hashlib.sha256(args.sim.read_bytes()).hexdigest() != build['simulator_sha256']:
    raise SystemExit('Simulator checksum does not match its build manifest')
for name in names:
    case = args.traces / name
    meta = json.loads((case / 'metadata.json').read_text())
    if meta['params_header_sha256'] != header_hash:
        raise SystemExit(f'{name}: command parameters differ from the generated hardware header')
    if meta['emission']['config']['max_bytes'] != build['configuration']['dma_max_bytes']:
        raise SystemExit(f'{name}: command generator and hardware DMA parameters differ')
    source_bytes = Path(meta['workload_manifest']).read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != meta['workload_manifest_sha256']:
        raise SystemExit(f'{name}: workload definition changed after command generation')
    source = json.loads(source_bytes)
    for file_key, hash_key in [('memory_file', 'memory_sha256'),
                               ('commands_file', 'commands_sha256'),
                               ('expected_output_file', 'expected_output_sha256')]:
        if hashlib.sha256((case / meta[file_key]).read_bytes()).hexdigest() != meta[hash_key]:
            raise SystemExit(f'{name}: {meta[file_key]} checksum mismatch')
    result_path = args.output / (name + '.json')
    output_tensor = meta['tensors']['output']
    command = [str(args.sim.resolve()), str((case / meta['memory_file']).resolve()),
               str(meta['memory_base']), str((case / meta['commands_file']).resolve()),
               str(output_tensor['address']), str(output_tensor['bytes']),
               str((case / meta['expected_output_file']).resolve()),
               str(meta['emission']['timed_start_record']), str(result_path.resolve()),
               *memory_service.simulator_arguments(selected_memory)]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (args.output / (name + '.log')).write_text(completed.stdout)
    status = [line for line in completed.stdout.splitlines() if line.startswith('GEMMINI_COMPARE_PASS')]
    print(name, status[-1] if status else completed.stdout[-2000:].strip(), flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)
    result = json.loads(result_path.read_text())
    memory_service.validate_result(result, selected_memory)
    if 'axi_max_beats' in build['configuration']:
        if (result['axi_data_bits'] != build['configuration']['dma_bus_bits'] or
                result['axi_strobe_bits'] * 8 != result['axi_data_bits'] or
                result['axi_max_beats'] != 256 or result['axi_boundary_bytes'] != 4096):
            raise SystemExit(f'{name}: observed AXI interface differs from the hardware configuration')
        if (result['max_read_burst_beats'] > 256 or result['max_write_burst_beats'] > 256 or
                sum(result['read_beats_by_beat_bytes'].values()) != result['read_beats'] or
                sum(result['write_beats_by_beat_bytes'].values()) != result['write_beats']):
            raise SystemExit(f'{name}: AXI beat accounting is inconsistent')
    observed_output_sha256 = hashlib.sha256(result_path.with_suffix('.output.bin').read_bytes()).hexdigest()
    if observed_output_sha256 != meta['expected_output_sha256']:
        raise SystemExit(f'{name}: observed output checksum differs from the independent reference')
    result.update(name=name, operation=meta['operation'], m=meta['m'], n=meta['n'], k=meta['k'],
                  macs=source['dense_macs'] if meta['operation'] == 'matmul' else source['useful_macs'],
                  workload_manifest_sha256=meta['workload_manifest_sha256'],
                  tensor_sha256={key: tensor['initial_sha256'] for key, tensor in meta['tensors'].items() if key != 'output'},
                  output_initial_sha256=meta['tensors']['output']['initial_sha256'],
                  expected_output_sha256=meta['expected_output_sha256'],
                  observed_output_sha256=observed_output_sha256,
                  commands_sha256=meta['commands_sha256'],
                  build_manifest_sha256=build_hash,
                  params_header_sha256=meta['params_header_sha256'],
                  dataflow=meta['emission']['dataflow'],
                  operand_storage_transpose=meta.get('transpose', 'none'),
                  tensor_alignment_bytes=meta.get('tensor_alignment_bytes', 64),
                  tensor_addresses={key: tensor['address'] for key, tensor in meta['tensors'].items()},
                  initial_memory_sha256=meta['memory_sha256'],
                  trace_metadata_sha256=hashlib.sha256((case / 'metadata.json').read_bytes()).hexdigest(),
                  explicit_tile=meta['emission'].get('explicit_tile'),
                  config=meta['emission']['config'])
    if 'selected_schedule' in meta:
        result['selected_schedule'] = meta['selected_schedule']
    result['effective_mac_utilization'] = result['macs'] / (256 * result['cycles'])
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    results.append(result)
(args.output / 'results.json').write_text(json.dumps({
    'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'build_manifest_sha256': build_hash,
    'configuration': build['configuration'],
    'memory_service': selected_memory,
    'cases': results}, indent=2) + '\n')
