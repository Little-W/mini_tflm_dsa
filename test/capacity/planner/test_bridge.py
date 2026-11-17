#!/usr/bin/env python3
"""Compare the fixed-width Python interface with native C result records."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rv32-report',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    source=ROOT/'scripts/capacity/device_planner.py'
    spec=importlib.util.spec_from_file_location('capacity_device_planner',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    inputs=[source,source.with_name('planner_bridge.c'),ROOT/'drivers/gempact_tiling.h',args.rv32_report]
    hashes={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    report=json.loads(args.rv32_report.read_text())
    records=report['reports']['current']['rows']
    checks=0
    for row in records:
        q=dict(zip(module.REQUEST_FIELDS,row['request']))
        memory=dict(zip(module.SHARED_FIELDS,row['shared_memory']))
        geometry=dict(zip(module.GEOMETRY_FIELDS,row['geometry']))
        actual=module.plan(q,memory if memory['total_bytes'] else None,
                           geometry if geometry['source_bytes'] else None)
        for field,expected in row['plan'].items():
            if field=='candidates_evaluated':continue
            parts=field.split('.')
            value=actual[parts[0]][parts[1]] if len(parts)>1 else actual[field]
            assert value==expected,(row['model'],row['operator'],field,value,expected)
            checks+=1
    assert hashes=={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    result={'passed':True,'requests':len(records),'compared_fields':checks,'source_sha256':hashes}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':True,'requests':len(records),'compared_fields':checks}))


if __name__=='__main__':main()
