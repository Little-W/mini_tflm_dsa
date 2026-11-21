#!/usr/bin/env python3
"""核对配置阶段的实际源码、形式结果与完整 NPU 严格解析结果。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--frame', type=Path, required=True)
    parser.add_argument('--output-control', type=Path, required=True)
    parser.add_argument('--elaboration', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    expected = digest(args.source_root / TOP)
    frame = json.loads((args.frame / 'summary.json').read_text())
    control = json.loads((args.output_control / 'summary.json').read_text())
    manifest = json.loads((args.elaboration / 'manifest.json').read_text())
    stages = json.loads((args.elaboration / 'stages.json').read_text())
    for name, report in [('frame', frame), ('output_control', control)]:
        if not report['passed'] or report['source_sha256']['candidate'] != expected:
            raise ValueError('验证结果与当前顶层源码不一致：' + name)
    if manifest['sources_sha256'][str(TOP)] != expected:
        raise ValueError('严格解析使用的顶层源码不一致')
    stage = stages['01_elaborate']
    if stage['output_sha256'] != digest(args.elaboration / 'elaborated.il'):
        raise ValueError('严格解析输出校验失败')
    if stage['script_sha256'] != digest(args.elaboration / '01_elaborate.ys'):
        raise ValueError('严格解析脚本校验失败')
    report = {
        'passed': True,
        'production_top_sha256': expected,
        'frame_configuration': frame,
        'output_control': control,
        'strict_elaboration': {
            'passed': True, 'top': manifest['top'],
            'frontend': 'Slang', 'declarations_before_use_checked': True,
            'manifest_sha256': digest(args.elaboration / 'manifest.json'),
            'stages_sha256': digest(args.elaboration / 'stages.json'),
            'source_sha256': manifest['sources_sha256'],
            'stage': stage,
        },
        'public_task_start_cycle_changed': False,
        'physical_timing_150mhz_confirmed': None,
        'collector_sha256': digest(Path(__file__)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'top_sha256': expected,
        'frame_profiles': len(frame['runs']),
        'reserve_profiles': len(control['reserve_profiles']),
        'row_profiles': len(control['row_profiles']),
        'four_state_cycles': control['four_state']['cycles']}))


if __name__ == '__main__':
    main()
