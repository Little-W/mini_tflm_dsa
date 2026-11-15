#!/usr/bin/env python3
"""Analyze IA slot residency prerequisites; this is not an RTL hit-rate model."""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GENERATED = ROOT / 'build/conv_models'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--models', type=Path, help='Optional generated model inventory; omitted means extract it now')
parser.add_argument('--stress-summary', type=Path,
                    help='Explicit R=2/W=2 stress experiment; not the production auto policy')
parser.add_argument('--driver-auto-summary', type=Path,
                    help='Production requested R=0/W=0 experiment')
parser.add_argument('--driver-tiling', type=Path,
                    help='Optional generated tiling; omitted means run the real production C oracle now')
parser.add_argument('--output', type=Path, default=ROOT / 'build/conv_reuse/real_layer_ia_geometry.json')
args = parser.parse_args()
if args.models is None:
    args.models = GENERATED / 'models.json'
    subprocess.run([sys.executable, HERE.parent / 'conv_models/extract_shapes.py', '--out', args.models], check=True)
if args.driver_tiling is None:
    args.driver_tiling = GENERATED / 'driver_tiling.json'
    subprocess.run([sys.executable, HERE.parent / 'conv_models/driver_tiling_oracle.py', '--models', args.models, '--out', args.driver_tiling], check=True)
catalogue_bytes = args.models.read_bytes()
catalogue = json.loads(catalogue_bytes)
size, slots, requested_r = 16, 4, 2
observed = {'stress_r2_w2': {}, 'driver_auto': {}}
summary_hashes = {}
production_tilings = {}
tiling_hash = None
if args.driver_tiling.exists():
    source = args.driver_tiling.read_bytes()
    tiling_hash = hashlib.sha256(source).hexdigest()
    production_tilings = {layer['layer_id']: layer['production_auto']
                          for layer in json.loads(source)['layers']}
for policy, path in [('stress_r2_w2', args.stress_summary),
                     ('driver_auto', args.driver_auto_summary)]:
    if path:
        source = path.read_bytes()
        summary_hashes[policy] = hashlib.sha256(source).hexdigest()
        observed[policy] = {layer['layer_id']: layer['tiling']
                            for layer in json.loads(source)['layers']}


def tap_gap(layer, axis):
    kh, kw = layer['filter_shape'][1:3]
    channels = layer['group_c']
    stride, dilation = layer['stride_hw'][axis], layer['dilation_hw'][axis]
    divisor = math.gcd(stride, dilation)
    tap_step, output_step = stride // divisor, dilation // divisor
    kernel_extent = (kh, kw)[axis]
    if tap_step >= kernel_extent or output_step >= layer['output_shape'][axis + 1]:
        return None
    gaps = set()
    for ky in range(kh - (tap_step if axis == 0 else 0)):
        for kx in range(kw - (tap_step if axis == 1 else 0)):
            for channel in range(channels):
                q = (ky * kw + kx) * channels + channel
                delta = tap_step * (kw if axis == 0 else 1) * channels
                gaps.add((q + delta) // size - q // size)
    return {'minimum_kernel_tap_step': tap_step,
            'corresponding_output_position_step': output_step,
            'q_tile_distance_values': sorted(gaps)}


rows = []
for layer in catalogue['layers']:
    positions = layer['output_shape'][1] * layer['output_shape'][2]
    row_tiles = (positions + size - 1) // size
    configured_r = min(requested_r, row_tiles)
    final_r = (row_tiles % configured_r) or configured_r
    reduction = layer['reduction_length']
    pointwise_dense = (layer['filter_shape'][1:3] == [1, 1]
                       and layer['stride_hw'] == [1, 1]
                       and all(layer['padding'][key] == 0
                               for key in ['top', 'left', 'bottom', 'right']))
    actual_auto = observed['driver_auto'].get(layer['layer_id'])
    oracle_auto = production_tilings.get(layer['layer_id'])
    if actual_auto and oracle_auto and actual_auto != oracle_auto:
        raise ValueError(f'Auto RTL tiling differs from C oracle: {layer["layer_id"]}')
    rows.append({
        'layer_id': layer['layer_id'],
        'recommended': layer['layer_id'] in catalogue['recommended_layer_ids'],
        'input_shape': layer['input_shape'], 'filter_shape': layer['filter_shape'],
        'output_shape': layer['output_shape'], 'stride_hw': layer['stride_hw'],
        'dilation_hw': layer['dilation_hw'], 'group_c': layer['group_c'],
        'output_positions': positions, 'row_tiles': row_tiles,
        'configured_r_after_small_shape_clamp': configured_r,
        'final_p_block_r': final_r,
        'q_tiles': (reduction + size - 1) // size,
        'horizontal_same_input_tap_distance': tap_gap(layer, 1),
        'vertical_same_input_tap_distance': tap_gap(layer, 0),
        'dense_pointwise_input_bytes_per_largest_p_block':
            min(positions, configured_r * size) * layer['group_c'] if pointwise_dense else None,
        'observed_test_tilings': {policy: values.get(layer['layer_id'])
                                 for policy, values in observed.items()},
        'production_c_tiling': oracle_auto,
    })
report = {
    'status': 'ANALYSIS_ONLY_NOT_AN_IA_REUSE_RTL_IMPLEMENTATION_OR_HIT_RATE',
    'models_source': str(args.models),
    'models_sha256': hashlib.sha256(catalogue_bytes).hexdigest(),
    'observed_test_tiling_source_sha256': summary_hashes,
    'production_c_tiling_source_sha256': tiling_hash,
    'assumptions': {'size': size, 'ia_slots': slots, 'requested_r': requested_r,
                    'task_config_constant': True},
    'limits': [
        'Tap distances describe the minimum useful displacement in one spatial axis at a fixed p block.',
        'They do not count hits, padding effects, actual bank availability, overwritten cells, or mixed-axis reuse.',
        'A source tile is age G*R_eff+i_current-i_source loads old; an age of 4 reaches the overwritten target slot.',
        'Earlier p-block tail taps may match new p-block boundary windows; q distance alone does not predict these hits.',
        'Observed output-column groups, if present, come from the raw-cache RTL experiment, not the proposed IA copy path.',
        'stress_r2_w2 explicitly requests R=2/W=2; only driver_auto represents production requested R=0/W=0.',
    ],
    'layers': rows,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + '\n')
for row in rows:
    if row['recommended']:
        def values(axis):
            gap = row[axis + '_same_input_tap_distance']
            return gap['q_tile_distance_values'] if gap else None
        print(row['layer_id'], 'R=', row['configured_r_after_small_shape_clamp'],
              'tail_R=', row['final_p_block_r'], 'q_tiles=', row['q_tiles'],
              'H=', values('horizontal'), 'V=', values('vertical'))
print(f'ANALYSIS_ONLY layers={len(rows)} output={args.output}')
