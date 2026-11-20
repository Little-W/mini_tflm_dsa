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
        try:
            relative_path = str(path.relative_to(root))
        except ValueError:
            relative_path = None
        source.append(dict(path=str(path), relative_path=relative_path,
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
    result = {}
    for delay_type in ('max', 'min'):
        paths = []
        for row in rows:
            if row['delay_type'] != delay_type:
                continue
            slack = number(row['slack_ns'])
            levels = int(row['logic_levels'])
            if levels < 0:
                raise ValueError('Logic level count must be nonnegative')
            paths.append(dict(slack_ns=slack, logic_levels=levels, clock=row['clock'],
                              startpoint=row['startpoint'], endpoint=row['endpoint']))
        result[delay_type] = dict(sampled_paths=len(paths),
                                  maximum_observed_logic_levels=max(
                                      (row['logic_levels'] for row in paths), default=None),
                                  worst_sampled_path=min(paths, key=lambda row: row['slack_ns'],
                                                         default=None))
    return result


def timing_summary(text):
    """Read global design setup/hold metrics, never substituting sampled paths."""
    fields = ('wns_ns', 'tns_ns', 'failing_endpoints', 'endpoints')
    result = {kind: dict.fromkeys(fields) for kind in ('max', 'min')}
    section = re.search(r'^\s*\|\s*Design Timing Summary\s*$', text, re.MULTILINE)
    if not section:
        return result
    lines = text[section.end():].splitlines()
    for index, line in enumerate(lines):
        if 'WNS(ns)' not in line or 'TNS Failing Endpoints' not in line:
            continue
        if index + 2 >= len(lines):
            return result
        separators = list(re.finditer(r'-+', lines[index + 1]))
        headers = [('max', ('WNS(ns)', 'TNS(ns)', 'TNS Failing Endpoints', 'TNS Total Endpoints')),
                   ('min', ('WHS(ns)', 'THS(ns)', 'THS Failing Endpoints', 'THS Total Endpoints'))]
        # Fixed-width columns preserve blanks for unavailable metrics.
        bounds = [(separators[i - 1].end() if i else 0, match.end())
                  for i, match in enumerate(separators)]
        for kind, names in headers:
            for field, name in zip(fields, names):
                position = line.find(name)
                column = next((i for i, (start, end) in enumerate(bounds)
                               if start <= position < end), None) if position >= 0 else None
                if column is None:
                    continue
                raw = lines[index + 2][bounds[column][0]:bounds[column][1]].strip()
                try:
                    value = number(raw)
                    if field in ('failing_endpoints', 'endpoints'):
                        if value < 0 or not value.is_integer():
                            continue
                        value = int(value)
                    result[kind][field] = value
                except ValueError:
                    pass
        break
    return result


def summarize(manifest, directory, stage, prefix='soc_top'):
    inputs = verify(manifest)
    directory = Path(directory)
    resources = utilization((directory / f'{prefix}_utilization.rpt').read_text())
    sampled = endpoint_statistics(directory / f'{prefix}_endpoints.tsv')
    summary_path = directory / f'{prefix}_timing_summary.rpt'
    timing = timing_summary(summary_path.read_text() if summary_path.is_file() else '')
    for kind in timing:
        timing[kind]['sample'] = sampled[kind]
    implementation = None
    if stage == 'routed':
        with (directory / 'implementation_checks.tsv').open() as stream:
            implementation = {row['check']: row['value'] for row in csv.DictReader(stream, delimiter='\t')}
    result = dict(schema_version=2, measurement_tool='Vivado', stage=stage,
                  source_manifest_sha256=digest(manifest), inputs_unchanged=True,
                  configuration=inputs['metadata'], git=inputs['git'], resources=resources,
                  timing=timing, implementation_checks=implementation,
                  requirements=dict(slice_luts_maximum=45000, clock_period_ns_maximum=6.667,
                                    combinational_logic_levels_maximum=None),
                  status=dict(slice_luts_within_limit=resources['slice_luts'] <= 45000,
                               observed_endpoint_paths_within_nine_levels=
                               (max(item['maximum_observed_logic_levels'] for item in sampled.values()) <= 9
                                if all(item['maximum_observed_logic_levels'] is not None
                                       for item in sampled.values()) else None),
                              all_connected_paths_within_nine_levels=None,
                              timing_150mhz_confirmed=
                              implementation.get('passed') == '1' if implementation else None),
                  timing_scope='WNS, TNS and endpoint counts are from the Vivado design timing summary; '
                               'null means unavailable. Path details are bounded samples.',
                  logic_level_scope='Maximum among sampled worst setup and hold paths only; '
                                    'the nine-level comparison is diagnostic, not an acceptance limit. '
                                    'Not a maximum over all endpoints or connected paths.',
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
