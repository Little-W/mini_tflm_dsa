#!/usr/bin/env python3
"""检查实际共享 RAM 的部分和写入、读取、回放及逐周期输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
REFERENCE="d4aabbb43147e0ef159439b20d1bee515535f49a"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--reference",default=REFERENCE)
    parser.add_argument("--verilator",default="verilator")
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    verilator=shutil.which(args.verilator)
    if not verilator:raise RuntimeError("找不到 Verilator")
    rows=[]
    for fpga in (False,True):
        name="fpga" if fpga else "generic";folder=out/name;folder.mkdir(exist_ok=True)
        flags=["-DSYNTHESIS=1","-DXILINX_FPGA=1"] if fpga else ["-USYNTHESIS","-UXILINX_FPGA"]
        wrapper=folder/"verilator_mode"
        wrapper.write_text("#!"+sys.executable+"\nimport os,sys\nargs=sys.argv[1:]\n"+
            "if '--getenv' not in args and '--version' not in args:\n    args += "+repr(flags)+"\n"+
            "os.execv("+repr(verilator)+",["+repr(verilator)+"]+args)\n")
        wrapper.chmod(0o755)
        command=[sys.executable,ROOT/"test/ps_request_ready/run_numeric.py","--reference",args.reference,
                 "--out",folder/"run","--verilator",wrapper,"--profiles","8192:7"]
        if fpga:command.append("--fpga")
        log=folder/"run.log"
        with log.open("w")as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600)
        result=json.loads((folder/"run/summary.json").read_text())
        if not result.get("passed"):raise RuntimeError("部分和数值检查未完成："+name)
        row=dict(fpga=fpga,passed=True,compile_options=flags,result=result,
                 log_sha256=digest(log),wrapper_sha256=digest(wrapper));rows.append(row)
        print(json.dumps(dict(fpga=fpga,passed=True,runs=result["runs"])),flush=True)
    (out/"summary.json").write_text(json.dumps(dict(passed=True,reference=args.reference,profiles=rows),
        ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":main()
