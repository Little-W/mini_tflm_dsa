#!/usr/bin/env python3
"""比较完整缓存状态、有效响应数据及响应队列实际保存的数据。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from run import prove_caches, prove_response
from support import ROOT, SOURCE, REFERENCE, check_sources, prepare_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--candidate', type=Path, default=ROOT / SOURCE)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=['2:1:1', '4:2:4'])
    parser.add_argument('--read-width', type=int, default=64)
    parser.add_argument('--line-bytes', type=int, default=16)
    args = parser.parse_args()
    out = args.out.resolve()
    _, paths, helpers, manifest = prepare_inputs(out, args.reference, args.candidate)
    report = {
        'passed': False,
        'inputs': manifest,
        'input_assumptions': [],
        'scope': {
            'control_and_state': 'Every public control/error output, common state and memory, request descriptions, response_push, and response queue contents',
            'core_payload': 'Compared for every core_rsp_valid cycle with unconstrained combinational inputs',
            'public_payload': 'rsp_data compared for every rsp_valid cycle, including response backpressure',
            'saved_payload': 'core_rsp_data compared whenever response_push saves the response queue entry',
        },
        'response_profiles': prove_response(out, paths, payload_when_valid=True),
        'complete_cache_profiles': prove_caches(out, paths, helpers, args.profiles,
                                                args.read_width, args.line_bytes,
                                                payload_when_valid=True),
    }
    check_sources(manifest)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out / 'summary.json')


if __name__ == '__main__':
    main()
