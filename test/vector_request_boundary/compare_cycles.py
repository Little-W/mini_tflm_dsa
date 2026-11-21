#!/usr/bin/env python3
"""按执行顺序比较完整向量任务，保留重复名称的测试项。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TRANSACTIONS = (
    'name', 'compute', 'read_bytes', 'write_bytes', 'bursts', 'quant_inputs',
    'write_bursts16', 'write_beats16', 'window_requests', 'window_completions',
    'window_response_beats',
)
PHASE_FIELDS = {'window_request_response_overlap'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(reference, selected, fixed_wait):
    previous = json.loads(reference.read_text())
    current = json.loads(selected.read_text())
    assert previous['stable_stimulus'] and current['stable_stimulus']
    assert len(previous['runs']) == len(current['runs'])
    rows, differences = [], {}
    for old_run, new_run in zip(previous['runs'], current['runs']):
        assert old_run['passed'] and new_run['passed']
        assert old_run['pe'] == new_run['pe'] and old_run['totals'] == new_run['totals']
        assert len(old_run['cases']) == len(new_run['cases'])
        for index, (old, new) in enumerate(zip(old_run['cases'], new_run['cases'])):
            assert all(old.get(field) == new.get(field) for field in TRANSACTIONS), (index, old, new)
            changed = {key: dict(reference=old.get(key), selected=new.get(key))
                       for key in set(old) | set(new) if old.get(key) != new.get(key)}
            if fixed_wait:
                assert set(changed) <= PHASE_FIELDS, (index, old['name'], changed)
            for field in changed:
                differences[field] = differences.get(field, 0) + 1
            rows.append(dict(pe=old_run['pe'], index=index, name=old['name'],
                             reference_cycles=old['cycles'], selected_cycles=new['cycles'],
                             differences=changed))
    return dict(passed=True, fixed_wait=fixed_wait, cases=len(rows),
                reference_sha256=digest(reference), selected_sha256=digest(selected),
                reference_total_cycles=sum(row['reference_cycles'] for row in rows),
                selected_total_cycles=sum(row['selected_cycles'] for row in rows),
                equal_transaction_fields=TRANSACTIONS, changed_fields=differences, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--selected', type=Path, required=True)
    parser.add_argument('--fixed-wait', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.reference, args.selected, args.fixed_wait)
    report['test_sha256'] = digest(Path(__file__))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'rows'}))


if __name__ == '__main__':
    main()
