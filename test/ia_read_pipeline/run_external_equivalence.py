#!/usr/bin/env python3
"""逐周期证明统一共享接口与指定提交的共享分支相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import input_files, with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='7ff66a59')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    modules = ('ia_loader_cache_mgr', 'ia_loader_ctrl', 'ia_loader')
    reference = []
    current = [ROOT / f'rtl/npu/loaders/{module}.sv' for module in modules]
    for module in modules:
        path = out / (module + '_reference.sv')
        path.write_bytes(subprocess.check_output(['git', 'show',
            args.reference_rev + f':rtl/npu/loaders/{module}.sv'], cwd=ROOT))
        reference.append(path)
    helpers = [path for path in with_dependencies(reference, ROOT) if path not in reference]
    helpers += [path for path in with_dependencies(current, ROOT) if path not in current]
    helpers = list(dict.fromkeys(helpers))
    for path in helpers:
        assert path.read_bytes() == subprocess.check_output(['git', 'show',
            args.reference_rev + ':' + str(path.relative_to(ROOT))], cwd=ROOT)
    sources = input_files([Path(__file__).resolve(), *current, *helpers], ROOT)
    source_hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    cases = []
    for lanes in (8, 16):
        for compact in (0, 1):
            cases.append((f'cache_dma{lanes}_compact{compact}', 'ia_loader_cache_mgr',
                ['-GSIZE=16', '-GDATA_WIDTH=16', '-GBUS_WIDTH=64', '-GCACHE_BLOCKS=32',
                 f'-GDMA_LANES={lanes}', f'-GCOMPACT_S8={compact}', '-GRAM_WORD_ADDR_WIDTH=12',
                 '-Gp_compact_offset_width=9', '-Gp_precomputed_slot_mask=1',
                 '-Gp_indexed_slot_rows=1', '-Gp_dma_source_layout=1', '-Gp_shared_write_stage=1']))
    reference_loader = reference[2].read_text()
    reference_loader = reference_loader.replace("    parameter bit EXTERNAL_RAM = 1'b0,\n", "")
    reference_loader = reference_loader.replace("        .EXTERNAL_RAM(EXTERNAL_RAM),\n", "")
    assert reference_loader == current[2].read_text()
    assert reference[1].read_bytes() == current[1].read_bytes()
    results = []
    for name, top, parameters in cases:
        commands = []
        for kind, files, extra in [('reference', reference, ['-GEXTERNAL_RAM=1']), ('current', current, [])]:
            rtl = with_dependencies(files, ROOT)
            options = ['read_slang', '--top', top, '-DSYNTHESIS=1', *parameters, *extra, *map(str, rtl)]
            commands.extend([' '.join(shlex.quote(item) for item in options),
                f'prep -top {top} -flatten', 'memory_map', 'opt', f'rename {top} {kind}',
                f'design -stash {kind}'])
        commands.extend(['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current', 'equiv_make reference current equivalent',
            'hierarchy -top equivalent', 'equiv_simple', 'equiv_induct -seq 3', 'equiv_status -assert'])
        script = out / (name + '.ys')
        script.write_text('\n'.join(commands) + '\n')
        log = out / (name + '.log')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        passed = result.returncode == 0 and 'Equivalence successfully proven!' in log.read_text()
        row = dict(case=name, passed=passed, script_sha256=digest(script), log_sha256=digest(log))
        results.append(row)
        print(json.dumps(row), flush=True)
        if not passed:
            raise RuntimeError('Equivalence did not complete: ' + str(log))
    if source_hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('RTL changed during equivalence checks')
    summary = dict(passed=True, reference_commit=subprocess.check_output(['git', 'rev-parse',
        args.reference_rev], cwd=ROOT, text=True).strip(), source_sha256=source_hashes, cases=results,
        reference_source_sha256={module: digest(path) for module, path in zip(modules, reference)},
        proof_scope=dict(cache='all public ports, sequential equivalence in four configurations',
            loader='source identical after removing the storage selection parameter and forwarding',
            loader_control='byte-identical source'),
        loader_body_matches_reference=True, loader_control_matches_reference=True,
        shared_helper_sources_match_reference=True)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
