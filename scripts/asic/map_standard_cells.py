#!/usr/bin/env python3
"""Map production NPU modules to a Liberty standard-cell library with Yosys/slang."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


PROFILES = {
    'ps_frame_store': {
        'top': 'ps_frame_store',
        'parameters': {
            'MAX_FRAME_ROWS': 256, 'FRAME_COUNT': 16, 'POOL_BYTES': 32768,
            'BANK_BYTES': 4096, 'EXTERNAL_RAM': 1, 'p_fixed_ps_channels': 1,
            'DIRECTORY_ROWS': 1024, 'RAM_ADDR_BITS': 12,
        },
        'boundary': 'External shared partial-sum RAM is represented by the existing RTL ports. '
                    'The decode FIFO, directory, and all other internal state are mapped.',
    },
    'vector_engine': {
        'top': 'vector_engine',
        'parameters': {
            'TILE': 16, 'BUS_WIDTH': 64, 'PE_COUNT': 16, 'WINDOW_LANES': 16,
            'SHARED_QUANT_ENABLE': 1, 'QUANT_LANES': 16,
            'SHARED_STORAGE_ENABLE': 1, 'SHARED_STORAGE_ADDR_WIDTH': 12,
        },
        'boundary': 'Shared weight and partial-sum storage, shared quantization, DMA, and '
                    'window service use their existing RTL ports. All internal state and '
                    'arithmetic are mapped.',
    },
}
for _registered in (0, 1):
    _suffix = 'registered' if _registered else 'fast'
    _common = {'p_size': 16, 'p_slot_w': 5, 'p_lanes': 16, 'p_line_bytes': 128,
               'p_register_descriptor': _registered}
    PROFILES[f'conv_descriptor_{_suffix}'] = {
        'top': 'conv_im2col_descriptor', 'parameters': dict(_common),
        'boundary': 'The descriptor module is measured at its existing frontend ports; '
                    'all internal state and combinational logic are mapped.',
    }
    PROFILES[f'conv_stream_{_suffix}'] = {
        'top': 'conv_im2col_stream',
        'parameters': dict(_common, p_bus_width=64,
                           p_register_cache_request=_registered,
                           p_register_row_address=_registered),
        'boundary': 'The stream module is measured at its existing frontend and cache '
                    'ports; all internal state and combinational logic are mapped.',
    }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote(value):
    token = str(value)
    if not re.fullmatch(r'[-A-Za-z0-9_./:+@=]+', token):
        raise ValueError('Yosys script paths must contain only portable filename characters: ' + token)
    return token


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def git_output(repo, *arguments):
    result = subprocess.run(['git', '-C', str(repo), *arguments],
                            text=True, capture_output=True, check=True)
    return result.stdout.strip()


def source_files(repo):
    sources = sorted(path for folder in ('rtl/npu', 'rtl/common')
                     for path in (repo / folder).rglob('*')
                     if path.suffix in ('.sv', '.v'))
    if not sources:
        raise ValueError('No production RTL sources found')
    sources.sort(key=lambda path: (not path.name.endswith('_pkg.sv'), str(path)))
    includes = sorted({path for path in (repo / 'include').rglob('*') if path.is_file()} |
                      {path for folder in ('rtl/npu', 'rtl/common')
                       for path in (repo / folder).rglob('*')
                       if path.suffix in ('.svh', '.vh')})
    return sources, includes


def liberty_cells(path):
    """Read cell areas and sequential classifications from Liberty cell groups."""
    text = path.read_text()
    starts = list(re.finditer(r'\bcell\s*\(\s*"?([^\s"()]+)"?\s*\)\s*\{', text))
    cells = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        body = text[match.end():end]
        area = re.search(r'\barea\s*:\s*([0-9.eE+-]+)\s*;', body)
        if not area:
            raise ValueError('Liberty cell has no area: ' + match[1])
        cells[match[1]] = {
            'area': float(area[1]),
            'sequential': bool(re.search(r'\b(?:ff|latch)\s*\(', body)),
        }
    if not cells:
        raise ValueError('No Liberty cells found')
    return cells


def worker(script):
    from pyosys import libyosys
    design = libyosys.Design()
    libyosys.run_pass('script ' + quote(script), design)
    return 0


def map_profile(args, name, sources, hashes, library, tools):
    profile = PROFILES[name]
    directory = args.out / name
    directory.mkdir(parents=True, exist_ok=True)
    constraints = directory / 'abc.constr'
    constraints.write_text(f'set_driving_cell {args.drive_cell}\n'
                           f'set_load {args.output_load_ff:g}\n')
    parameters = ' '.join('-G ' + key + '=' + str(value)
                          for key, value in profile['parameters'].items())
    input_sources = ' '.join(quote(path.relative_to(args.repo)) for path in sources)
    script = directory / 'synth.ys'
    script.write_text(
        f'read_slang --top {profile["top"]} --threads 1 --single-unit '
        f'--ignore-assertions --allow-use-before-declare -I include {parameters} {input_sources}\n'
        f'hierarchy -check -top {profile["top"]}\n'
        f'synth -top {profile["top"]} -flatten -noabc\n'
        'delete t:$scopeinfo\n'
        'check -assert\n'
        f'dfflibmap -liberty {quote(args.liberty)}\n'
        f'abc -exe {quote(args.abc)} -liberty {quote(args.liberty)} '
        f'-constr {quote(constraints)} -D {args.target_ps:g}\n'
        'clean\n'
        f'read_liberty -lib {quote(args.liberty)}\n'
        f'hierarchy -check -top {profile["top"]}\n'
        'check -assert -mapped\n'
        f'tee -o {quote(directory / "stat.json")} stat -json -liberty {quote(args.liberty)}\n'
        f'write_verilog -noattr -simple-lhs {quote(directory / "mapped.v")}\n'
        f'write_json {quote(directory / "mapped.json")}\n')
    metadata = {
        'profile': name, **profile,
        'source_commit': git_output(args.repo, 'rev-parse', 'HEAD'),
        'tracked_source_tree_clean': not git_output(args.repo, 'status', '--porcelain',
                                                     '--untracked-files=no'),
        'source_sha256': hashes,
        'runner_sha256': digest(Path(__file__).resolve()),
        'library': {'name': args.liberty.name, 'sha256': digest(args.liberty)},
        'tools': tools,
        'mapping_constraints': {
            'input_driving_cell': args.drive_cell, 'output_load_ff': args.output_load_ff,
            'abc_delay_target_ps': args.target_ps,
        },
        'storage': 'Internal memories are lowered to standard cells. External services '
                   'remain top-level ports; no design modules are blackboxed.',
        'defines': ['SYNTHESIS (read_slang default)'],
        'start_time_utc': datetime.now(timezone.utc).isoformat(),
    }
    write_json(directory / 'input.json', metadata)
    started = time.monotonic()
    command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(script)]
    environment = os.environ.copy()
    environment.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    with (directory / 'synthesis.log').open('w') as log:
        completed = subprocess.run(command, cwd=args.repo, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   timeout=args.timeout)
    if completed.returncode:
        raise RuntimeError(f'Synthesis failed for {name}; see {directory / "synthesis.log"}')
    changed = [path for path, expected in hashes.items()
               if digest(args.repo / path) != expected]
    if changed:
        raise RuntimeError('Production source changed during synthesis: ' + ', '.join(changed))
    design = json.loads((directory / 'mapped.json').read_text())
    module = design['modules'][profile['top']]
    counts = Counter(cell['type'] for cell in module['cells'].values())
    unknown = set(counts) - set(library)
    if unknown:
        raise RuntimeError('Unmapped or non-library cell types: ' + ', '.join(sorted(unknown)))
    if module.get('memories') or module.get('processes'):
        raise RuntimeError('Memory or process remains after standard-cell mapping')
    if not counts:
        raise RuntimeError('Mapped module is empty')
    sequential = sum(count for name, count in counts.items() if library[name]['sequential'])
    ports = {port: {'direction': value['direction'], 'width': len(value['bits'])}
             for port, value in module['ports'].items()}
    result = {
        **metadata, 'passed': True, 'elapsed_seconds': time.monotonic() - started,
        'sources_unchanged_during_mapping': True,
        'standard_cell_count': sum(counts.values()),
        'sequential_cell_count': sequential,
        'combinational_cell_count': sum(counts.values()) - sequential,
        'cell_counts': dict(sorted(counts.items())),
        'cell_area_library_units': sum(count * library[name]['area']
                                       for name, count in counts.items()),
        'ports': ports,
        'unmapped_cell_types': [], 'design_blackboxes': [],
        'artifact_sha256': {filename: digest(directory / filename) for filename in
                            ('mapped.v', 'mapped.json', 'stat.json', 'synth.ys', 'abc.constr',
                             'synthesis.log')},
    }
    write_json(directory / 'result.json', result)
    print(f'MAP_PASS profile={name} cells={result["standard_cell_count"]} '
          f'sequential={sequential} area={result["cell_area_library_units"]:.6f}', flush=True)
    return {'profile': name, 'passed': True, 'result': name + '/result.json',
            'result_sha256': digest(directory / 'result.json'),
            'standard_cell_count': result['standard_cell_count'],
            'sequential_cell_count': sequential,
            'cell_area_library_units': result['cell_area_library_units']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path)
    parser.add_argument('--liberty', type=Path)
    parser.add_argument('--abc', type=Path, help='Default: yosys-abc bundled with pyosys')
    parser.add_argument('--profiles', nargs='+', choices=tuple(PROFILES), default=list(PROFILES))
    parser.add_argument('--jobs', type=int, choices=(1, 2), default=1)
    parser.add_argument('--target-ps', type=float, default=6000)
    parser.add_argument('--drive-cell', default='BUF_X1')
    parser.add_argument('--output-load-ff', type=float, default=5)
    parser.add_argument('--timeout', type=float, default=7200)
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker.resolve())
    if args.out is None or args.liberty is None:
        parser.error('--out and --liberty are required')
    if args.target_ps <= 0 or args.output_load_ff < 0 or args.timeout <= 0:
        parser.error('Timing target and timeout must be positive; load must be nonnegative')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', args.drive_cell):
        parser.error('Invalid driving-cell identifier')
    from pyosys import libyosys
    args.repo = args.repo.resolve()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    args.liberty = args.liberty.resolve()
    args.abc = (args.abc or Path(libyosys.__file__).parent / 'yosys-abc').resolve()
    library = liberty_cells(args.liberty)
    if args.drive_cell not in library:
        parser.error('Driving cell is absent from the selected Liberty library')
    if not args.abc.is_file():
        parser.error('ABC executable does not exist')
    sources, includes = source_files(args.repo)
    hashes = {str(path.relative_to(args.repo)): digest(path) for path in sources + includes}
    tools = {'pyosys_version': version('pyosys'),
             'libyosys_sha256': digest(Path(libyosys.__file__)),
             'abc_sha256': digest(args.abc), 'python_version': sys.version.split()[0]}
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        pending = {executor.submit(map_profile, args, name, sources, hashes, library, tools): name
                   for name in dict.fromkeys(args.profiles)}
        for future in as_completed(pending):
            results.append(future.result())
    order = {name: index for index, name in enumerate(args.profiles)}
    results.sort(key=lambda result: order[result['profile']])
    write_json(args.out / 'summary.json', {
        'passed': all(result['passed'] for result in results),
        'source_commit': git_output(args.repo, 'rev-parse', 'HEAD'),
        'profiles': results,
        'scope': 'Module standard-cell mapping at existing RTL ports. Timing analysis '
                 'requires the mapped netlist and the same Liberty library.',
    })
    return 0


if __name__ == '__main__':
    sys.exit(main())
