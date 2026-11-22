#!/usr/bin/env python3
"""验证准备列数、字内范围、输出状态和范围保存关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    results={}
    for name,entry in [('arithmetic','test/frontend_pipeline/check_arithmetic.py'),
                       ('stream','test/frontend_group_feedback/stream_control.py')]:
        folder=out/name
        subprocess.run([sys.executable,str(ROOT/entry),'--source-root',str(args.source_root.resolve()),
                        '--out',str(folder)],cwd=ROOT,check=True)
        result=json.loads((folder/'summary.json').read_text())
        if not result['passed']:raise RuntimeError(str(folder))
        results[name]=result
    (out/'summary.json').write_text(json.dumps({'passed':True,'checks':results},indent=2)+'\n')

if __name__=='__main__':main()
