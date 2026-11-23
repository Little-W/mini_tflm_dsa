#!/usr/bin/env python3
"""Verify PS observer event ordering against the production frame store."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import runpy
import subprocess
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reader = runpy.run_path(str(source/'scripts/rtl/source_files.py'))
    rtl = reader['with_dependencies']([source/'rtl/npu/ps_compact/ps_frame_store.sv'], source)
    sources = [repo/'test/ps_stream_capture/tb.sv', repo/'test/ps_compression/ps_stream_capture.sv', *rtl]
    verifier = repo/'test/ps_compression/stream_soc_trace.py'
    files = [Path(__file__).resolve(), verifier, *sources]
    before = {str(p): digest(p) for p in files}
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
               '--top-module', 'ps_stream_capture_tb', '--Mdir', str(out/'obj'),
               '-j', str(args.jobs), *map(str, sources)]
    with (out/'compile.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = out/'obj/Vps_stream_capture_tb'
    event_file = out/'events.txt'
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    result = subprocess.run([str(binary), '+PS_EVENTS='+str(event_file)], capture_output=True, text=True)
    log = result.stdout + result.stderr
    (out/'run.log').write_text(log)
    assert result.returncode == 0 and 'PS_CAPTURE_OVERLAP_PASS' in log, log
    sys.path.insert(0, str(verifier.parent))
    import stream_soc_trace
    checked = stream_soc_trace.verify(event_file, log)
    rejected = []
    for number, expected in ((1, 'PS INT32 mismatch'), (2, 'Invalid PS observer descriptor'),
                             (3, 'Incomplete PS frame at completion')):
        result = subprocess.run([str(binary), f'+FAULT_CASE={number}'], capture_output=True, text=True)
        text = result.stdout + result.stderr
        (out/f'assertion_{number}.log').write_text(text)
        assert result.returncode != 0 and expected in text, text
        rejected.append({'case': number, 'expected_assertion': expected, 'rejected': True})
    assert before == {str(p): digest(p) for p in files}
    report = {'passed': True, 'rtl_source_commit': subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
        'source_sha256': before, 'binary_sha256': digest(binary), 'compile_command': command,
        'event_verification': checked, 'assertion_cases': rejected}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'passed': True, 'summary': checked['summary'], 'assertion_cases': len(rejected)}))


if __name__ == '__main__':
    main()
