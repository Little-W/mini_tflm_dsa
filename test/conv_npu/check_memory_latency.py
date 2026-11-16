#!/usr/bin/env python3
"""Check precise synchronous AXI read latency and overlapping request waits."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root/'test/conv_npu/axi_memory.sv', root/'test/conv_npu/tb_axi_memory_latency.sv']
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
               '--top-module', 'tb_axi_memory_latency', '--Mdir', str(out/'obj'), '-j', str(args.jobs),
               '-CFLAGS', '-std=c++20 -O1', '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0', *map(str, sources)]
    with (out/'build.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    binary = out/'obj/Vtb_axi_memory_latency'
    result = subprocess.run([str(binary), '+NO_RANDOM_WAIT'], capture_output=True, text=True, timeout=60)
    (out/'run.log').write_text(result.stdout+result.stderr)
    rows = [dict((k, int(v)) for k, v in re.findall(r'(\w+)=(\d+)', line))
            for line in result.stdout.splitlines() if line.startswith('MEMORY_LATENCY_PASS')]
    passed = result.returncode == 0 and len(rows) == 10 and 'AXI_MEMORY_LATENCY_PASS' in result.stdout
    summary = {'passed': passed, 'bus_width': 64, 'registered_synchronous_read': True,
               'read_latency_semantics': 'per_request_from_ar_handshake',
               'read_beat_interval_cycles': 1, 'cases': sorted(rows, key=lambda x:(x['latency'],x['outstanding'])),
               'command': command, 'source_sha256': {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
               'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary['cases'], indent=2))
    if not passed:
        print(result.stdout+result.stderr)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
