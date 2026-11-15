#!/usr/bin/env python3
"""Offline request model for the committed implicit-im2col/IA scheduling RTL.

This produces addresses, not clock cycles. It models the frontend's persistent
4-byte holding register; one event is one cache request, never one scalar byte.
"""
from collections import Counter
from dataclasses import asdict, dataclass
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LINE_BYTES = 16
WORD_BYTES = 4


def generated_layers(out, selected=None, *, metadata_only=True):
    """Read checked-in TFLite geometry and call the current C planner at runtime."""
    sys.path.insert(0, str(ROOT / 'test/conv_models'))
    from generate_vectors import generate_layers
    return generate_layers(Path(out), selected=selected, metadata_only=metadata_only)


@dataclass(frozen=True)
class Request:
    index: int
    address: int
    word: int
    line: int
    position: int
    reduction: int
    row_group: int
    output_group: int
    reduction_tile: int
    position_tile: int


def generate_requests(layer):
    geometry = layer['model_layer']
    _, height, width, channels = geometry['input_shape']
    _, output_h, output_w, _ = geometry['output_shape']
    _, kernel_h, kernel_w, _ = geometry['filter_shape']
    stride_h, stride_w = geometry['stride_hw']
    dilation_h, dilation_w = geometry['dilation_hw']
    top, left = geometry['padding']['top'], geometry['padding']['left']
    base = layer['tensors']['input']['address']
    reuse = layer['tiling']['ia_reuse']
    output_groups = layer['tiling']['col_groups']
    size = layer['size']
    positions = output_h * output_w
    group_c, group_offset = layer['parameters'][3:5]
    reduction = kernel_h * kernel_w * group_c
    last_word = None
    result = []
    # IA loader iteration: L2 rows -> output column group -> L1 reduction
    # tile -> R loaded position tiles. Prefetch changes timing, not this order.
    for row_group, group_p0 in enumerate(range(0, positions, reuse * size)):
        for output_group in range(output_groups):
            for q_tile, q0 in enumerate(range(0, reduction, size)):
                for p0 in range(group_p0, min(group_p0 + reuse * size, positions), size):
                    for p in range(p0, min(p0 + size, positions)):
                        oy, ox = divmod(p, output_w)
                        for q in range(q0, min(q0 + size, reduction)):
                            tap, channel = divmod(q, group_c)
                            ky, kx = divmod(tap, kernel_w)
                            iy = oy * stride_h + ky * dilation_h - top
                            ix = ox * stride_w + kx * dilation_w - left
                            if not (0 <= iy < height and 0 <= ix < width):
                                continue
                            address = base + (iy * width + ix) * channels + group_offset + channel
                            word = address // WORD_BYTES
                            if word == last_word:
                                continue
                            last_word = word
                            result.append(Request(len(result), address, word,
                                                  address // LINE_BYTES, p, q,
                                                  row_group, output_group, q_tile, p0 // size))
    return result


def transfer_bounds(block, block_bytes, layer):
    start = layer['tensors']['input']['address']
    end = start + layer['tensors']['input']['bytes']
    return max(start, block * block_bytes), min(end, (block + 1) * block_bytes)


def lru(requests, layer, capacity, ways=2):
    sets = capacity // (LINE_BYTES * ways)
    resident = [dict() for _ in range(sets)]
    hits = misses = read_bytes = 0
    histogram = Counter()
    for event in requests:
        entries = resident[event.line % sets]
        if event.line in entries:
            hits += 1
        else:
            misses += 1
            if len(entries) == ways:
                del entries[min(entries, key=entries.get)]
            lo, hi = transfer_bounds(event.line, LINE_BYTES, layer)
            read_bytes += hi - lo
            histogram.update(range(lo, hi))
        entries[event.line] = event.index
    return {'hits': hits, 'misses': misses, 'input_bytes': read_bytes,
            'input_unique': len(histogram), 'input_duplicate': read_bytes - len(histogram),
            'input_max_reads': max(histogram.values(), default=0)}, histogram


def bypass(requests, layer):
    histogram = Counter()
    for event in requests:
        lo, hi = transfer_bounds(event.word, WORD_BYTES, layer)
        histogram.update(range(lo, hi))
    total = sum(histogram.values())
    return {'hits': 0, 'misses': len(requests), 'input_bytes': total,
            'input_unique': len(histogram), 'input_duplicate': total - len(histogram),
            'input_max_reads': max(histogram.values(), default=0)}, histogram


def save_trace(path, requests):
    fields = list(Request.__dataclass_fields__)
    text = [','.join(fields)]
    text.extend(','.join(str(v) for v in asdict(event).values()) for event in requests)
    data = ('\n'.join(text) + '\n').encode()
    path.write_bytes(gzip.compress(data, mtime=0))
    return {'events': len(requests), 'uncompressed_sha256': hashlib.sha256(data).hexdigest(),
            'compressed_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/conv_replacement/traces')
    parser.add_argument('--layers', nargs='+')
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    bundle = generated_layers(args.out / 'geometry', args.layers)
    report = {'method': 'runtime forward geometry/schedule request enumeration, including the persistent 4-byte word holder',
              'scope': 'offline address model; use rtl_compare.py for current RTL and per-byte histogram validation',
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'rtl_executed': False, 'layers': []}
    for layer in bundle['layers']:
        requests = generate_requests(layer)
        lo = layer['tensors']['input']['address']
        hi = lo + layer['tensors']['input']['bytes']
        assert all(lo <= req.address < hi and req.index == i for i, req in enumerate(requests))
        path = args.out / (layer['layer_slug'] + '.requests.csv.gz')
        trace = save_trace(path, requests)
        capacities = {}
        for capacity in (256, 512, 1024, 2048, 4096):
            capacities[str(capacity)] = lru(requests, layer, capacity)[0]
        report['layers'].append({'layer_id': layer['layer_id'], 'tiling': layer['tiling'],
                                 'trace': path.name, **trace, 'lru': capacities,
                                 'bypass': bypass(requests, layer)[0]})
        print('TRACE_GENERATED', layer['layer_id'], len(requests), 'requests', flush=True)
    report['passed'] = True
    report['layer_count'] = len(report['layers'])
    (args.out / 'trace_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('TRACE_GENERATION_PASS', report['layer_count'])


if __name__ == '__main__':
    main()
