#!/usr/bin/env python3
"""Export verified INT8 Add tensors from a prepared model for RTL replay."""
from pathlib import Path
import hashlib
import json
import math
import struct


def prepare_replay(model_dir: Path, destination: Path) -> dict:
    model_dir = model_dir.resolve()
    manifest_path = model_dir / 'manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['rounding_mode'] != 'nearest_even':
        raise ValueError('Add replay requires nearest-even references')
    tensors = {item['index']: item for item in manifest['graph']['tensors']}
    operations = [item for item in manifest['graph']['nodes'] if item['op'] == 'ADD']
    records, payload = [], bytearray()

    def tensor_bytes(item):
        data = (model_dir / item['path']).read_bytes()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError(f'Tensor identity differs: {item["path"]}')
        return data

    for sample in manifest['samples']:
        reference = json.loads(tensor_bytes(sample['reference']))
        values = {item['tensor_index']: item for item in [reference['input'], *reference['nodes']]}
        by_index = {item['index']: item for item in reference['nodes']}
        for node in operations:
            if len(node['inputs']) != 2 or len(node['outputs']) != 1:
                raise ValueError('Add replay requires two inputs and one output')
            ta, tb = [tensors[index] for index in node['inputs']]
            tc = tensors[node['outputs'][0]]
            if any(item['dtype'] != 'int8' for item in (ta, tb, tc)) or not ta['shape'] == tb['shape'] == tc['shape']:
                raise ValueError('Add replay requires equal-shaped INT8 tensors')
            za, zb, zc = [item['zero_points'][0] for item in (ta, tb, tc)]
            activation = node['options']['fused_activation_function']
            if activation not in ('NONE', 'RELU'):
                raise ValueError(f'Unsupported replay activation: {activation}')
            lower = max(-128, zc) if activation == 'RELU' else -128
            expected = by_index[node['index']]
            quant = expected['integer_parameters']
            ma, mb, mc = quant['multipliers']
            sa, sb, sc = quant['shifts']
            params = [-za, -zb, ma, sa, mb, sb, quant['left_shift'], mc, sc, zc, lower, 127]
            inputs = [values[index] for index in node['inputs']]
            data_a, data_b, data_out = [tensor_bytes(item) for item in (*inputs, expected)]
            length = math.prod(tc['shape'])
            if not length == len(data_a) == len(data_b) == len(data_out):
                raise ValueError('Add replay tensor sizes differ')
            name = f'{manifest["name"]}_sample{sample["sample_index"]}_node{node["index"]}'
            encoded = name.encode('ascii')
            payload += struct.pack('<I', len(encoded)) + encoded
            payload += struct.pack('<I12i', length, *params)
            payload += data_a + data_b + data_out
            records.append({'name': name, 'length': length, 'parameters': params,
                            'input1': inputs[0], 'input2': inputs[1], 'output': expected})
    if not records:
        raise ValueError('Prepared model contains no Add tensors')
    complete = b'VCEADD1\0' + struct.pack('<I', len(records)) + payload
    destination.write_bytes(complete)
    metadata = {'model_manifest': str(manifest_path),
                'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                'replay_sha256': hashlib.sha256(complete).hexdigest(),
                'records': records, 'outputs': sum(item['length'] for item in records)}
    destination.with_suffix('.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata
