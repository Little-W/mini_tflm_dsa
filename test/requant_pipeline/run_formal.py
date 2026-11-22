#!/usr/bin/env python3
"""证明两级量化移位的完整商、最近偶数增量与任意使能暂停。"""
from pathlib import Path
import argparse, hashlib, json, shlex, subprocess, sys
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/writeback/requant_shift_pipeline.sv',HERE/'shift_formal.sv']
    hashes={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    script=out/'proof.ys';log=out/'proof.log'
    script.write_text('read_slang --top shift_proof '+shlex.join(map(str,sources))+'\n'+
        'prep -top shift_proof -flatten\nmemory_map\nchformal -lower\nopt -full\n'+
        'sat -seq 3 -tempinduct -maxsteps 5 -set-at 1 rst_n 0 -prove-asserts -verify -timeout 60\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
            stdout=stream,stderr=subprocess.STDOUT,check=True)
    assert 'Induction step proven' in log.read_text()
    assert hashes=={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    result={'passed':True,'source_sha256':hashes,'input_product_bits':64,'input_amount_bits':7,
        'latency_enabled_edges':2,'clock_enable_constrained':False,'properties':2,
        'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
