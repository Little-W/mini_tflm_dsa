#!/usr/bin/env python3
"""保存 Vivado 输入文件指纹，并从原生利用率与端点报告生成测量结果。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def snapshot(inputs, output):
    entries = list(csv.reader(Path(inputs).read_text().splitlines(), delimiter='\t'))
    if any(len(row) != 2 for row in entries):
        raise ValueError('Each input record must contain a key and a value')
    metadata, paths = {}, set()
    for key, value in entries:
        if key == 'source':
            paths.add(Path(value).resolve())
        elif key == 'include_dir':
            directory = Path(value).resolve()
            if not directory.is_dir():
                raise ValueError(f'Include directory does not exist: {directory}')
            paths.update(path.resolve() for path in directory.rglob('*')
                         if path.suffix in ('.vh', '.svh') and path.is_file())
        else:
            if key in metadata:
                raise ValueError(f'Duplicate input property: {key}')
            metadata[key] = value
    if not paths:
        raise ValueError('No synthesis input files were recorded')
    root = Path(metadata['repository']).resolve()
    source = []
    for path in sorted(paths):
        if not path.is_file():
            raise ValueError(f'Synthesis input does not exist: {path}')
        source.append(dict(path=str(path), relative_path=str(path.relative_to(root))
                           if path.is_relative_to(root) else None,
                           sha256=digest(path), bytes=path.stat().st_size))
    git = {}
    for key, arguments in (('commit', ['rev-parse', 'HEAD']),
                           ('tree', ['rev-parse', 'HEAD^{tree}']),
                           ('worktree_status', ['status', '--porcelain=v1'])):
        result = subprocess.run(['git', '-C', str(root), *arguments],
                                text=True, capture_output=True, check=False)
        git[key] = result.stdout.strip() if result.returncode == 0 else None
    value = dict(schema_version=1, flow='Vivado native RTL', metadata=metadata,
                 git=git, inputs=source, input_records_sha256=digest(inputs))
    save(output, value)
    return value


def verify(manifest):
    value = json.loads(Path(manifest).read_text())
    changed = [row['path'] for row in value['inputs']
               if not Path(row['path']).is_file() or digest(row['path']) != row['sha256']]
    if changed:
        raise ValueError('Synthesis inputs changed during the run:\n' + '\n'.join(changed))
    return value


def number(text):
    value = float(text.replace(',', '').strip())
    if not math.isfinite(value):
        raise ValueError('Report values must be finite')
    return value


def utilization(text):
    rows = {}
    for line in text.splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) < 4 or fields[0] or fields[-1]:
            continue
        label = re.sub(r'\s*\*\s*$', '', fields[1])
        if re.fullmatch(r'[0-9][0-9,.]*', fields[2]):
            rows[label] = number(fields[2])
    aliases = {
        'slice_luts': ('Slice LUTs', 'CLB LUTs'),
        'logic_luts': ('LUT as Logic',),
        'memory_luts': ('LUT as Memory',),
        'slice_registers': ('Slice Registers', 'CLB Registers'),
        'bram_tiles': ('Block RAM Tile',),
        'ramb36': ('RAMB36/FIFO', 'RAMB36'),
        'ramb18': ('RAMB18',),
        'dsps': ('DSPs', 'DSP48E1'),
    }
    result = {}
    for key, names in aliases.items():
        values = [rows[name] for name in names if name in rows]
        if not values:
            raise ValueError(f'Missing Vivado utilization field: {key}')
        result[key] = values[0] if key == 'bram_tiles' else int(values[0])
        if key != 'bram_tiles' and result[key] != values[0]:
            raise ValueError(f'Expected an integer utilization value: {key}')
    if result['logic_luts'] + result['memory_luts'] != result['slice_luts']:
        raise ValueError('Logic and memory LUT counts do not add up to total Slice LUTs')
    if result['ramb36'] + result['ramb18'] / 2 != result['bram_tiles']:
        raise ValueError('BRAM counts do not add up to Block RAM Tile utilization')
    return result


def endpoint_statistics(path):
    with Path(path).open() as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    if not rows:
        raise ValueError('No timed endpoints were reported')
    result = {}
    for delay_type in ('max', 'min'):
        endpoints = {}
        for row in rows:
            if row['delay_type'] != delay_type:
                continue
            slack = number(row['slack_ns'])
            levels = int(row['logic_levels'])
            if levels < 0:
                raise ValueError('Logic level count must be nonnegative')
            # 同一捕获引脚在多个时钟下出现时保留各时钟关系中的最差结果。
            key = (row['clock'], row['endpoint'])
            previous = endpoints.get(key)
            if previous is None or slack < previous['slack_ns']:
                endpoints[key] = dict(slack_ns=slack, logic_levels=levels,
                                      startpoint=row['startpoint'], endpoint=row['endpoint'])
        if not endpoints:
            raise ValueError(f'No {delay_type} timing endpoints were reported')
        values = list(endpoints.values())
        result[delay_type] = dict(wns_ns=min(row['slack_ns'] for row in values),
                                 tns_ns=sum(min(0.0, row['slack_ns']) for row in values),
                                 endpoints=len(values),
                                 failing_endpoints=sum(row['slack_ns'] < 0 for row in values),
                                 maximum_observed_logic_levels=max(row['logic_levels'] for row in values),
                                 worst_path=min(values, key=lambda row: row['slack_ns']))
    return result


def summarize(manifest, directory, stage, prefix='soc_top'):
    inputs = verify(manifest)
    directory = Path(directory)
    resources = utilization((directory / f'{prefix}_utilization.rpt').read_text())
    timing = endpoint_statistics(directory / f'{prefix}_endpoints.tsv')
    implementation = None
    if stage == 'routed':
        with (directory / 'implementation_checks.tsv').open() as stream:
            implementation = {row['check']: row['value'] for row in csv.DictReader(stream, delimiter='\t')}
    result = dict(schema_version=1, measurement_tool='Vivado', stage=stage,
                  source_manifest_sha256=digest(manifest), inputs_unchanged=True,
                  configuration=inputs['metadata'], git=inputs['git'], resources=resources,
                  timing=timing, implementation_checks=implementation,
                  requirements=dict(slice_luts_maximum=45000, clock_period_ns_maximum=6.667,
                                    combinational_logic_levels_maximum=9),
                  status=dict(slice_luts_within_limit=resources['slice_luts'] <= 45000,
                              observed_endpoint_paths_within_nine_levels=
                              max(item['maximum_observed_logic_levels'] for item in timing.values()) <= 9,
                              all_connected_paths_within_nine_levels=None,
                              timing_150mhz_confirmed=
                              implementation.get('passed') == '1' if implementation else None),
                  logic_level_scope='Worst setup and hold path per timed endpoint and capture clock; '
                                    'all connected alternatives require a separate structural path analysis',
                  reports_sha256={path.name: digest(path) for path in sorted(directory.iterdir())
                                  if path.is_file() and path.suffix in ('.rpt', '.tsv')})
    save(directory / 'measurement.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    collect = commands.add_parser('snapshot')
    collect.add_argument('--inputs', required=True, type=Path)
    collect.add_argument('--out', required=True, type=Path)
    check = commands.add_parser('verify')
    check.add_argument('--manifest', required=True, type=Path)
    report = commands.add_parser('summarize')
    report.add_argument('--manifest', required=True, type=Path)
    report.add_argument('--directory', required=True, type=Path)
    report.add_argument('--stage', required=True, choices=('synthesized', 'routed'))
    report.add_argument('--prefix', choices=('soc_top', 'fpga_top'), default='soc_top')
    args = parser.parse_args()
    if args.command == 'snapshot':
        value = snapshot(args.inputs, args.out)
        print(json.dumps(dict(inputs=len(value['inputs']), manifest=str(args.out))))
    elif args.command == 'verify':
        value = verify(args.manifest)
        print(json.dumps(dict(inputs=len(value['inputs']), unchanged=True)))
    else:
        value = summarize(args.manifest, args.directory, args.stage, args.prefix)
        print(json.dumps(dict(resources=value['resources'], status=value['status'])))


if __name__ == '__main__':
    main()
