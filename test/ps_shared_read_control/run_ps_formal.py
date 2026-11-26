#!/usr/bin/env python3
"""证明部分和读取资格保持完整帧存储的状态、存储内容及公开输出。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "d4aabbb43147e0ef159439b20d1bee515535f49a"
SOURCE = Path("rtl/npu/ps_compact/ps_frame_store.sv")
sys.path.insert(0, str(ROOT))
from scripts.rtl.source_files import input_files, with_dependencies
CASES = dict(runpy.run_path(str(ROOT / "test/ps_frame_ready/run_full.py"))["CASES"])
CASES["odd_frames"] = ("ps_frame_store", str(SOURCE), dict(MAX_FRAME_ROWS=47,
    FRAME_COUNT=3, POOL_BYTES=4096, BANK_BYTES=2048, EXTERNAL_RAM=0))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--reference",default=REFERENCE)
    parser.add_argument("--jobs",type=int,default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    dependencies = with_dependencies([ROOT/SOURCE],ROOT)
    hashes = {str(path.relative_to(ROOT)):digest(path) for path in input_files(dependencies,ROOT)}
    source_sets = {}
    for variant in ("reference","candidate"):
        text = (subprocess.check_output(["git","show",args.reference+":"+str(SOURCE)],cwd=ROOT,text=True)
                if variant=="reference" else (ROOT/SOURCE).read_text())
        path = out/(variant+".sv")
        path.write_text(text)
        source_sets[variant] = with_dependencies([path],ROOT)

    def prove(job):
        name,fpga = job
        parameters = CASES[name][2]
        label = name+("_fpga" if fpga else "_generic")
        flags = ["-DSYNTHESIS=1","-DXILINX_FPGA=1"] if fpga else ["-USYNTHESIS","-UXILINX_FPGA"]
        flags += [f"-G{key}={value}" for key,value in parameters.items()]
        commands = []
        for variant in ("reference","candidate"):
            commands += ["read_slang --top ps_frame_store "+shlex.join(flags+list(map(str,source_sets[variant]))),
                         "setattr -mod -unset keep_hierarchy","setattr -unset keep_hierarchy",
                         "prep -top ps_frame_store -flatten","memory_map","async2sync","opt_clean",
                         "rename ps_frame_store "+variant,"design -stash "+variant]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from candidate -as candidate candidate",
                     "equiv_make reference candidate proof","hierarchy -top proof",
                     "equiv_simple -seq 1","opt_clean","equiv_induct -seq 3","equiv_status -assert"]
        script,log = out/(label+".ys"),out/(label+".log")
        script.write_text("\n".join(commands)+"\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable,ROOT/"scripts/fpga/open_fpga_synth.py","--worker",script],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600)
        text = log.read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven",text)
        if not match or int(match[2]) or "Equivalence successfully proven!" not in text:
            raise RuntimeError("完整部分和帧存储检查未完成："+label)
        row = dict(profile=name,fpga=fpga,parameters=parameters,passed=True,
                   proven_bits=int(match[1]),log_sha256=digest(log),script_sha256=digest(script))
        print(json.dumps(row),flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(prove,((name,fpga) for name in CASES for fpga in (False,True))))
    if hashes != {name:digest(ROOT/name) for name in hashes}:
        raise RuntimeError("验证期间 RTL 内容发生变化")
    report = dict(passed=True,reference=args.reference,source_sha256=hashes,
                  input_constraints=None,handshake_constraints=None,
                  all_public_outputs_and_state_compared=True,all_memory_contents_compared=True,
                  profiles=rows,proven_bits=sum(row["proven_bits"] for row in rows))
    (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    main()
