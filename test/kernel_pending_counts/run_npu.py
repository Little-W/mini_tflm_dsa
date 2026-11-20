#!/usr/bin/env python3
"""在完整 NPU 中检查受管卷积预取、返回归属和错误后的新配置。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test/ps_compression'))
from run_shared_npu import configure, npu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sim = args.sim.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((sim / 'build.json').read_text())
    expected = {'returncode': 0, 'size': 16, 'shared_bank_bytes': 8192,
                'shared_bank_count': 7, 'ps_compress': True, 'force_raw': True,
                'pool_bytes': 49152}
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f'Simulator parameter {key} differs from {value}')
    for name, expected_hash in manifest['source_sha256'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f'Simulator source differs: {name}')
    binary = sim / 'obj/Vtb_conv_npu'
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest['binary_sha256']:
        raise RuntimeError('Simulator executable differs from its manifest')
    if 'test/monitors/kernel_loader_observer.sv' not in manifest['source_sha256']:
        raise RuntimeError('Simulator must include the loader protocol assertions')
    case_root = out / 'cases'
    case_root.mkdir(exist_ok=True)
    reference = npu.make_reference(out)
    cases = []
    for mode in (0, 1):
        for error in (0, 3, 0):
            name = f'conv_{mode}_sequence_{len(cases)}'
            directory = npu.task(case_root, 16, reference, name=name,
                h=9, w=7, c=6, kh=3, kw=3, co=35, ph=1, pw=1,
                dataflow=mode, requested_r=2, requested_w=3,
                error=error, inject=bool(error), seed=193 + len(cases))
            cases.append(configure(directory, banks=1, r=2, w=3, control=2,
                                   bank_bytes=8192, bank_count=7))
    result = npu.run_suite(binary, out, 'managed_convolution', cases, timeout=900)
    log = (out / 'managed_convolution.log').read_text()
    matches = re.findall(r'KERNEL_PENDING_PROTOCOL_PASS ([^\n]+)', log)
    if not result['passed'] or len(matches) != 1:
        raise RuntimeError('Managed convolution validation did not pass')
    coverage = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', matches[0])}
    if not all(coverage[name] > 0 for name in ('managed', 'prefetch', 'hits')):
        raise RuntimeError('Managed prefetch and cache-hit coverage is required')
    if not sum(row['kernel_im2col_commands'] for row in result['measurements']):
        raise RuntimeError('The kernel loader must execute image descriptors')
    report = {'passed': True, 'cases': len(cases), 'coverage': coverage,
              'int32_checks': sum(row['int32_checks'] for row in result['measurements']),
              'simulator_manifest': str(sim / 'build.json'),
              'simulator_manifest_sha256': hashlib.sha256((sim / 'build.json').read_bytes()).hexdigest(),
              'results': result}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({name: value for name, value in report.items() if name != 'results'}))


if __name__ == '__main__':
    main()
