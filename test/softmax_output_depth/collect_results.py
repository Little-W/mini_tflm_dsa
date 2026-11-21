#!/usr/bin/env python3
"""核对 Softmax 功能验证和结构测量是否使用同一份 RTL。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_softmax.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--measurement', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    validation = json.loads(args.validation.read_text())
    measurement = json.loads(args.measurement.read_text())
    sha = digest(ROOT / SOURCE)
    if validation['passed'] is not True or validation['source_sha256'][SOURCE] != sha:
        raise RuntimeError('功能验证源码或通过状态不匹配')
    if len(validation['runs']) != 12 or not all(run['passed'] for run in validation['runs']):
        raise RuntimeError('完整配置等价检查不完整')
    if validation['four_state']['passed'] is not True:
        raise RuntimeError('四态检查不完整')
    numeric = validation.get('numeric', {}).get('runs', [])
    if len(numeric) != 4 or not all(run['passed'] for run in numeric):
        raise RuntimeError('整数数值验证不完整')
    for label in ('reference', 'current'):
        part = measurement[label]
        expected = sha if label == 'current' else validation['reference_source_sha256'][SOURCE]
        matches = [value for name, value in part['source_manifest']['sources_sha256'].items()
                   if name.endswith(SOURCE)]
        if matches != [expected] or part['register_paths']['graph_complete'] is not True:
            raise RuntimeError('测量源码或完整图状态不匹配：' + label)
    result = dict(passed=True, source_sha256={SOURCE: sha}, functional=validation,
        measurement=measurement, numerical_totals={key: sum(run[key] for run in numeric)
            for key in ('cases', 'elements', 'cycles', 'lut_requests')},
        input_reports_sha256={str(args.validation): digest(args.validation),
                              str(args.measurement): digest(args.measurement)},
        physical_timing_confirmed=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, source_sha256=sha, **result['numerical_totals'])))


if __name__ == '__main__':
    main()
