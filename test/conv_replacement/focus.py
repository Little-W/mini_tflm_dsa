#!/usr/bin/env python3
"""OFFLINE: line-event admission with an explicitly charged 16-byte transient.

The transient is invalidated on every different-line request, including main-
cache hits. It only combines consecutive words of the current line; it is not
an extra retained fully-associative cache entry. No new policy RTL is simulated.
"""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

from trace_model import ROOT, LINE_BYTES, generate_requests, generated_layers, lru


FOCUS = ['justure_detect:sg0:op7', 'justure_detect:sg0:op16', 'mobilenet_v2:sg0:op52']


def line_events(requests):
    events = []
    for request in requests:
        if not events or events[-1]['line'] != request.line:
            events.append({'index': len(events), 'line': request.line,
                           'first_request': request.index, 'word_requests': 0,
                           'position': request.position, 'reduction': request.reduction,
                           'row_group': request.row_group, 'output_group': request.output_group})
        events[-1]['word_requests'] += 1
    return events


def simulate(events, capacity, policy, mapping='low', ways=2, *, return_histogram=False):
    lines = [event['line'] for event in events]
    count = len(lines)
    sets = capacity // (LINE_BYTES * ways)
    if sets & (sets - 1):
        raise ValueError('power-of-two number of sets required')
    shift = (sets - 1).bit_length()
    next_use = [count] * count
    next_at = {}
    for i in range(count - 1, -1, -1):
        line = lines[i]
        next_use[i] = next_at.get(line, count)
        next_at[line] = i
    remaining = Counter(lines)
    resident = [dict() for _ in range(sets)]
    hits = misses = admissions = bypasses = 0
    histogram = Counter()
    for i, line in enumerate(lines):
        low = line & (sets - 1)
        set_id = low ^ ((line >> shift) & (sets - 1)) if mapping == 'xor' else low
        entries = resident[set_id]
        remaining[line] -= 1
        next_at[line] = next_use[i]
        if line in entries:
            hits += 1
            entries[line] = i
            continue
        misses += 1
        histogram.update(range(line * LINE_BYTES, (line + 1) * LINE_BYTES))
        victim = None
        if policy != 'lru' and remaining[line] == 0:
            bypasses += 1
            continue
        if len(entries) == ways:
            if policy == 'lru':
                victim = min(entries, key=entries.get)
            elif policy == 'next_use_admission':
                victim = max(entries, key=lambda x: (next_at[x], -entries[x]))
                if next_at[line] >= next_at[victim]:
                    bypasses += 1
                    continue
            elif policy == 'future_count_admission':
                # Pure exact remaining-event count; ties keep existing lines.
                # Resident ties fall back to LRU, rather than secretly using
                # exact next-use information as a second oracle.
                victim = min(entries, key=lambda x: (remaining[x], entries[x]))
                if remaining[line] <= remaining[victim]:
                    bypasses += 1
                    continue
            else:
                raise ValueError(policy)
        if victim is not None:
            del entries[victim]
        entries[line] = i
        admissions += 1
    result = {'main_cache_bytes': capacity, 'transient_bytes': LINE_BYTES,
            'total_data_bytes': capacity + LINE_BYTES, 'ways': ways, 'sets': sets,
            'mapping': mapping, 'policy': policy, 'line_events': count,
            'line_hits': hits, 'line_misses': misses, 'line_admissions': admissions,
            'transient_only_lines': bypasses, 'input_read_bytes': misses * LINE_BYTES,
            'unique_input_bytes': len(set(lines)) * LINE_BYTES,
            'duplicate_input_bytes': (misses - len(set(lines))) * LINE_BYTES}
    return (result, histogram) if return_histogram else result


def live_bound(events, capacities):
    lines = [event['line'] for event in events]
    last = {line: i for i, line in enumerate(lines)}
    live = set()
    seen = set()
    peak = 0
    per_mapping = {}
    for capacity in capacities:
        sets = capacity // 32
        shift = (sets - 1).bit_length()
        for mapping in ['low', 'xor']:
            resident_live = [0] * sets
            highest = 0
            visited = set()
            for i, line in enumerate(lines):
                low = line & (sets - 1)
                set_id = low ^ ((line >> shift) & (sets - 1)) if mapping == 'xor' else low
                if line not in visited:
                    visited.add(line)
                    if last[line] != i:
                        resident_live[set_id] += 1
                if last[line] == i and i != lines.index(line):
                    resident_live[set_id] -= 1
                highest = max(highest, resident_live[set_id])
            per_mapping[f'{capacity}B_{mapping}'] = highest
    for i, line in enumerate(lines):
        if line not in seen:
            seen.add(line)
            if last[line] != i:
                live.add(line)
        if last[line] == i:
            live.discard(line)
        peak = max(peak, len(live))
    counts = Counter(lines)
    return {'peak_lines_live_between_first_and_last_event': peak,
            'fully_associative_main_bytes_for_one_fill_per_line_lower_bound': peak * 16,
            'max_simultaneous_live_lines_in_one_set': per_mapping,
            'max_total_events_per_line': max(counts.values()),
            'max_remaining_events_after_current': max(counts.values()) - 1,
            'remaining_after_event_bits_per_resident_line': max(1, (max(counts.values()) - 1).bit_length()),
            'count_including_current_bits': max(counts.values()).bit_length(),
            'next_event_rank_bits_per_resident_line': len(lines).bit_length(),
            'domain': '16-byte whole-line fills, optional admission, transient only current consecutive line; not a lower bound for arbitrary word-granular storage'}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/conv_replacement/model')
    parser.add_argument('--capacities', nargs='+', type=int, default=[256, 512, 1024, 2048])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    bundle = generated_layers(args.out / 'geometry', FOCUS)
    result = {'verification_level': 'OFFLINE MODEL ONLY; geometry and production C tiling generated on this invocation',
              'new_policy_rtl_executed': False,
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'transient_rule': '16 bytes extra; invalidated on first request to any different line, even on main-cache hit; no retained extra line',
              'next_use_rule': 'after the complete current line event; never the next word of the same line',
              'rows': [], 'layers': []}
    for layer in bundle['layers']:
        requests = generate_requests(layer)
        events = line_events(requests)
        if any(event['word_requests'] != 4 for event in events):
            raise AssertionError('focus fast-path event is not exactly a full 16-byte line')
        bounds = live_bound(events, args.capacities)
        result['layers'].append({'layer_id': layer['layer_id'], 'word_requests': len(requests),
                                 'line_events': len(events), 'tiling': layer['tiling'], **bounds})
        for capacity in args.capacities:
            cases = [('lru', 'low', 2), ('lru', 'xor', 2), ('future_count_admission', 'low', 2),
                     ('next_use_admission', 'low', 2), ('next_use_admission', 'xor', 2),
                     ('next_use_admission', 'low', capacity // 16)]
            for policy, mapping, ways in cases:
                measured = simulate(events, capacity, policy, mapping, ways)
                measured['layer_id'] = layer['layer_id']
                if policy == 'lru' and mapping == 'low':
                    old = lru(requests, layer, capacity)[0]
                    assert measured['line_misses'] == old['misses']
                    assert measured['input_read_bytes'] == old['input_bytes']
                result['rows'].append(measured)
            group = result['rows'][-6:]
            print('MODEL', layer['layer_id'], capacity,
                  [(x['policy'], x['mapping'], x['ways'], x['input_read_bytes']) for x in group], flush=True)
    (args.out / 'line_event_focus.json').write_text(json.dumps(result, indent=2) + '\n')
    with (args.out / 'line_event_focus.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result['rows'][0]))
        writer.writeheader()
        writer.writerows(result['rows'])


if __name__ == '__main__':
    main()
