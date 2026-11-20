#!/usr/bin/env python3
"""检查新增输出寄存对四态数据、有效标志和异步复位的行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from run_formal import CORE, ROOT, extracted_stage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    source=(ROOT/CORE).read_text()
    extracted=out/'output_stage.sv'
    extracted.write_text(extracted_stage(source,'current_stage'))
    test=Path(__file__).with_name('tb_four_state.sv')
    binary=out/'run.vvp'
    commands=[['iverilog','-g2012','-s','output_four_state_tb','-o',str(binary),str(extracted),str(test)],
              ['vvp',str(binary)]]
    for command,log in zip(commands,('compile.log','run.log')):
        with (out/log).open('w') as stream:
            subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
    report=json.loads(next(line for line in (out/'run.log').read_text().splitlines() if line.startswith('{')))
    report.update(source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  extracted_source_sha256=hashlib.sha256(extracted.read_bytes()).hexdigest(),
                  testbench_sha256=hashlib.sha256(test.read_bytes()).hexdigest(),
                  commands=commands,scope='四态数据及 valid/tile_done 逐拍捕获，复位异步清零有效标志')
    if source!=(ROOT/CORE).read_text():
        raise RuntimeError('Source changed during four-state check')
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
