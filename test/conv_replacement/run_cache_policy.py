#!/usr/bin/env python3
"""Exercise current cache admission/error/backpressure RTL with generated stimuli."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/conv_replacement/cache_policy')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--reuse-build-root', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sim = shutil.which(args.verilator)
    if not sim:
        raise SystemExit('Verilator required')
    sources = [(ROOT / 'rtl/npu/dma' / name if name.startswith('cache/') else ROOT / 'rtl/npu/conv' / name) for name in (
        'cache/conv_sdp_ram.sv', 'conv_axi_span_reader.sv', 'cache/conv_read_cache.sv')]
    sources += [ROOT / 'test/conv_reuse/axi_counted_memory.sv', HERE / 'tb_cache_policy.sv']
    import runpy
    sources = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](sources)
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    report = {'scope': 'actual cache RTL with deterministic procedural stimuli and manually supplied next-use hints',
              'status': 'FAIL', 'simulator': subprocess.check_output([sim, '--version'], text=True).strip(),
              'source_sha256': hashes}
    binary = out / 'obj/Vtb_cache_policy'
    try:
        if args.skip_build:
            existing = args.reuse_build_root.resolve() if args.reuse_build_root else out
            manifest = json.loads((existing / 'status.json').read_text())
            if manifest.get('status') != 'PASS' or manifest['source_sha256'] != hashes:
                raise RuntimeError('cached executable source hashes or previous build status differ')
            binary = existing / 'obj/Vtb_cache_policy'
            if not binary.is_file():
                raise RuntimeError(f'cached executable missing: {binary}')
            report.update(command=manifest['command'], warnings=manifest['warnings'],
                          reused_build=str(existing))
        else:
            command = [sim, '--binary', '--timing', '--assert', '-DCONV_ASSERT', '-Wall', '-Wno-fatal',
                       '--top-module', 'tb_cache_policy', '--Mdir', str(out / 'obj'), '-j', '2'] + list(map(str, sources))
            report['command'] = command
            with (out / 'build.log').open('w') as stream:
                subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            build = (out / 'build.log').read_text()
            warnings = [s for s in build.splitlines() if s.startswith('%Warning')]
            reviewed = {'BLKSEQ', 'PROCASSINIT', 'UNUSEDSIGNAL', 'UNUSEDPARAM', 'SYNCASYNCNET'}
            unexpected = [s for s in warnings if s.split(':', 1)[0].removeprefix('%Warning-') not in reviewed]
            if unexpected:
                raise RuntimeError('unreviewed lint diagnostics: ' + repr(unexpected))
            report['warnings'] = warnings
        with (out / 'run.log').open('w') as stream:
            subprocess.run([str(binary)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=60)
        output = (out / 'run.log').read_text()
        if hashes != {str(p.relative_to(ROOT)): sha(p) for p in sources}:
            raise RuntimeError('sources changed during validation')
        report.update(status='PASS', binary_sha256=sha(binary),
                      summary=next(s for s in output.splitlines() if s.startswith('CACHE_POLICY_PASS')),
                      cases=[s for s in output.splitlines() if s.startswith('CACHE_POLICY_CASE')])
    except (subprocess.SubprocessError, OSError, RuntimeError, StopIteration) as exc:
        report['reason'] = str(exc)
    (out / 'status.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in {'source_sha256', 'command', 'cases'}}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
