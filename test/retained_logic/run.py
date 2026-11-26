#!/usr/bin/env python3
"""检查综合保留属性调整后的全部功能语句，并运行公共加法器验证。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def functional_tokens(text):
    text = re.sub(r'/\*.*?\*/|//[^\n]*|\(\*.*?\*\)', ' ', text, flags=re.S)
    # 保留属性的高字节别名只连接原有信号，没有功能消费者。
    text = re.sub(r'logic\s+\[2\*(?:BUS_WIDTH|BYTE_PER_BEAT)-1:(?:8|1)\]\s+'
        r'low_shifted_upper_(?:data|mask)\s*;', '', text)
    text = re.sub(r'assign\s+low_shifted_upper_(?:data|mask)\s*=\s*'
        r'low_shifted_(?:data|mask)\[[^\]]*\]\s*;', '', text)
    text = text.replace('logic rd_rsp_count_zero, rd_rsp_plain_equal;\n    logic rd_rsp_count_one;',
        'logic rd_rsp_count_zero, rd_rsp_count_one, rd_rsp_plain_equal;')
    return re.sub(r'\s+', '', text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='df08ac08')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for source in ('rtl/common/parallel_prefix_add.sv', 'rtl/npu/dma/axi_linear_block_dma.sv'):
        original = subprocess.check_output(['git', 'show', args.reference+':'+source], cwd=ROOT, text=True)
        current = (ROOT/source).read_text()
        if source.endswith('axi_linear_block_dma.sv'):
            for name in ('low_shifted_upper_data', 'low_shifted_upper_mask'):
                if len(re.findall(r'\b'+name+r'\b', current)) != 2:
                    raise RuntimeError('保留属性别名存在额外消费者：'+name)
        if functional_tokens(original) != functional_tokens(current):
            raise RuntimeError('功能语句存在差异：'+source)
        records.append({'source': source, 'functional_tokens_identical': True,
            'source_sha256': hashlib.sha256(current.encode()).hexdigest()})
        if source.endswith('parallel_prefix_add.sv'):
            (out/'reference.sv').write_text(original)
    subprocess.run([sys.executable, ROOT/'test/common_prefix_tree/run.py',
        '--reference', out/'reference.sv', '--out', out/'prefix', '--jobs', '2'], check=True)
    summary = json.loads((out/'prefix/summary.json').read_text())
    result = {'passed': True, 'attribute_only': records,
        'formal_profiles': len(summary['two_state']['profiles']),
        'four_state_comparisons': sum(x['checked'] for x in summary['four_state']['profiles'])}
    (out/'validation.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
