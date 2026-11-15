#!/usr/bin/env python3
"""Check configured A/B/PS RAM sizes in a real Verilator JSON elaboration.

Requires a Verilator supporting --json-only (validated with 5.48).  This is an
optional RTL check, separate from the standard-library software tests.  It
counts the elaborated behavioral RAM declarations, not SRAM macro area.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
from capacity import config as capacity_config  # noqa: E402


def children(node):
    for value in node.values():
        if isinstance(value,list):
            yield from (child for child in value if isinstance(child,dict))
        elif isinstance(value,dict):
            yield value


def ram_inventory(tree):
    refs={}

    def index(node):
        if "addr" in node:
            refs[node["addr"]]=node
        for child in children(node):
            index(child)
    index(tree)

    @lru_cache(None)
    def width(ref):
        node=refs[ref]
        kind=node["type"]
        if kind=="BASICDTYPE":
            if "range" not in node:
                return 1
            left,right=map(int,node["range"].split(":"))
            return abs(left-right)+1
        if kind in ("UNPACKARRAYDTYPE","PACKARRAYDTYPE"):
            left,right=map(int,node["declRange"].strip("[]").split(":"))
            return (abs(left-right)+1)*width(node["refDTypep"])
        if kind in ("REFDTYPE","ENUMDTYPE","CONSTDTYPE"):
            return width(node["refDTypep"])
        raise ValueError("Unsupported Verilator dtype: "+kind)

    totals={"a_panel_bytes":0,"b_panel_bytes":0,"ps_pool_bytes":0}
    counts={key:0 for key in totals}

    def module(module_node):
        origin=module_node.get("origName",module_node["name"])

        def scan(node):
            if node.get("type")=="CELL":
                module(refs[node["modp"]])
                return
            if node.get("type")=="VAR":
                key=None
                if origin=="gempact_panel_cache":
                    key={"aram":"a_panel_bytes","bram":"b_panel_bytes"}.get(node.get("name"))
                elif origin=="gempact_ps_bank" and node.get("name")=="ram":
                    key="ps_pool_bytes"
                if key:
                    bits=width(node["dtypep"])
                    if bits%8:
                        raise ValueError("RAM declaration is not byte aligned")
                    totals[key]+=bits//8
                    counts[key]+=1
            for child in children(node):
                scan(child)
        scan(module_node)

    top=next(node for node in tree["modulesp"] if node.get("level")==1)
    module(top)
    return totals,counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=ROOT/"config/npu.mk")
    parser.add_argument("--verilator",default="verilator")
    parser.add_argument("--output-root",type=Path,default=ROOT/"build/capacity/elaboration")
    parser.add_argument("--keep-tree",action="store_true",help="Keep the rebuildable, relatively large AST JSON")
    args=parser.parse_args()
    values=capacity_config.validate_config(capacity_config.read_config(args.config),require_pcr=True)
    out=args.output_root.resolve();out.mkdir(parents=True,exist_ok=True)
    work=out/"obj";work.mkdir(exist_ok=True)
    tree_path=out/"elaborated.tree.json"
    npu=ROOT/"rtl/npu"
    sources=sorted(npu.rglob("*.sv"))+sorted(npu.rglob("*.v"))
    sources += [ROOT/"rtl/common/pseudo_dual_port_ram.v",ROOT/"rtl/axi_top/npu_axil_top.sv",
                ROOT/"rtl/axi_top/npu_axil_reg_if.sv"]
    command=[args.verilator,"--json-only","--assert","-Wno-fatal","--top-module","npu_axil_top",
             "--json-only-output",str(tree_path),"--Mdir",str(work),
             "-GDATA_WIDTH=8","-GWEIGHT_WIDTH=8",f'-GSIZE={values["SIZE"]}',
             f'-GIA_CACHE_BLOCKS={values["IA_CACHE_BLOCKS"]}',
             f'-GPS_FRAME_COUNT={values["PS_FRAME_COUNT"]}',
             f'-GAXI_READ_OUTSTANDING={values["AXI_READ_OUTSTANDING"]}',
             "-I"+str(npu/"gempact"),"-DGEMPACT_PANEL_ENGINE","-DGEMMORA_INT8_PROFILE=1",
             "-DGEMMORA_PS_SECTOR_CODEC","-DGEMPACT_PCR_PS","-DGEMPACT_PCR_ENABLE=1",
             "-DGEMPACT_PCR_FAST_ENABLE=1",f'-DGEMMORA_PS_POOL_BYTES={values["PS_POOL_BYTES"]}',
             f'-DGEMPACT_PANEL_MAX_R={values["PANEL_MAX_R"]}',
             f'-DGEMPACT_PANEL_MAX_W={values["PANEL_MAX_W"]}']
    if values["PS_FORCE_RAW"]:
        command.append("-DGEMMORA_PS_FORCE_RAW")
    command += list(map(str,sources))
    with (out/"elaboration.log").open("w") as log:
        run=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    if run.returncode:
        print(f"Verilator elaboration failed; see {out/'elaboration.log'}",file=sys.stderr)
        return run.returncode
    totals,counts=ram_inventory(json.loads(tree_path.read_text()))
    expected={"a_panel_bytes":16*128*values["PANEL_MAX_R"],
              "b_panel_bytes":16*32*values["PANEL_MAX_W"]*4,
              "ps_pool_bytes":values["PS_POOL_BYTES"]}
    matched=totals==expected and counts["a_panel_bytes"]==16 and counts["b_panel_bytes"]==16
    result={"passed":matched,"scope":"Elaborated behavioral A/B/PS RAM declarations; excludes other state and physical SRAM rounding.",
            "configuration":values,"expected":expected,"elaborated":totals,"declaration_counts":counts,
            "configuration_sha256":hashlib.sha256(args.config.read_bytes()).hexdigest(),
            "verilator":subprocess.check_output([args.verilator,"--version"],text=True).strip(),
            "command":command,
            "sources_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (out/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    if not args.keep_tree:
        tree_path.unlink()
    print(json.dumps({"passed":matched,"elaborated":totals,"result":str(out/"result.json")},indent=2))
    return 0 if matched else 1


if __name__=="__main__":
    raise SystemExit(main())
