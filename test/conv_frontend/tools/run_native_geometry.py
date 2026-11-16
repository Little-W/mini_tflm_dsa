#!/usr/bin/env python3
"""Verify native geometry prediction and IA writes for cache policies 1 and 2."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_rtl import FILES, OUTPUT, ROOT


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_vectors(path: Path) -> None:
    values = list(range(-8, 8))
    # NHWC 1x1x16, 1x1 kernel, one output position, one native IA tile.
    fields = [4096, 1, 1, 16, 16, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 16]
    path.write_text('1\n' + ' '.join(map(str, fields)) + '\n' +
                    ' '.join(f'{value & 255:02x}' for value in values) + '\n' +
                    '0 0 1 0\n' + ' '.join(map(str, values)) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policies', type=int, choices=(1, 2), nargs='+', default=[1, 2])
    parser.add_argument('--out', type=Path, default=OUTPUT / 'native_geometry')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    vectors = out / 'native_1x1_c16_vectors.txt'
    write_vectors(vectors)
    sources = [Path(name) if Path(name).is_absolute() else ROOT / name for name in FILES]
    sources += [Path(__file__).resolve(), Path(__file__).with_name('run_rtl.py').resolve()]
    hashes = {str(path.relative_to(ROOT.parents[1])): digest(path) for path in sources}
    results = []
    for policy in dict.fromkeys(args.policies):
        target = out / f'policy{policy}'
        target.mkdir(exist_ok=True)
        command = [sys.executable, str(ROOT / 'tools/run_rtl.py'), '--size', '16',
                   '--cache-policy', str(policy), '--cache-sets', '128', '--cache-ways', '2',
                   '--line-bytes', '16', '--windowed', '--prefetch',
                   '--native-sched-r', '1', '--native-sched-groups', '1',
                   '--expect-geometry-predictions', '1', '--max-cycles', '2000',
                   '--vectors', str(vectors), '--out', str(target)]
        with (target / 'driver.log').open('w') as stream:
            process = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        status_path = target / 'rtl_status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        passed = process.returncode == 0 and status.get('status') == 'PASS'
        summary = []
        if status.get('log'):
            summary = [line for line in Path(status['log']).read_text().splitlines()
                       if line.startswith(('RTL_NATIVE_GEOMETRY_PASS', 'RTL_FRONTEND_PASS'))]
        result = {'policy': policy, 'passed': passed, 'command': command,
                  'status_file': str(status_path), 'summary': summary}
        results.append(result)
        print(json.dumps(result), flush=True)
    unchanged = all(digest(path) == hashes[str(path.relative_to(ROOT.parents[1]))] for path in sources)
    passed = unchanged and all(result['passed'] for result in results)
    report = {'passed': passed, 'scope': 'Production frontend RTL with native scheduler metadata',
              'case': {'input_shape': [1, 1, 16], 'kernel': [1, 1],
                       'output_spatial_shape': [1, 1], 'ia_tile_shape': [1, 16],
                       'input_base': 4096, 'input_offset': 0, 'native_sched_r': 1,
                       'native_sched_groups': 1, 'tile_p0': 0, 'tile_q0': 0,
                       'tile_rows': 1, 'tile_columns': 16, 'expected_geometry_predictions': 1,
                       'windowed': True, 'prefetch': True, 'max_cycles': 2000},
              'vector_file': str(vectors), 'vector_sha256': digest(vectors),
              'source_sha256': hashes, 'sources_unchanged_during_run': unchanged, 'results': results}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
