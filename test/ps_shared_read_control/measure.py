#!/usr/bin/env python3
"""成对测量完整 PS 帧存储和共享通道的读取控制及错误状态路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "d4aabbb43147e0ef159439b20d1bee515535f49a"
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"scripts/fpga"))
from scripts.rtl.source_files import with_dependencies, input_files
from netlist_metrics import connected_paths, register_origins

PROFILES = {
    "ps": ("ps_frame_store","rtl/npu/ps_compact/ps_frame_store.sv",
           dict(MAX_FRAME_ROWS=256,FRAME_COUNT=16,POOL_BYTES=49152,
                BANK_BYTES=8192,EXTERNAL_RAM=1,p_fixed_ps_channels=1)),
    "shared": ("ia_ps_channel_ram","rtl/npu/buffers/ia_ps_channel_ram.sv",
               dict(p_bank_bytes=8192,p_total_bytes=57344,p_shared_write_stage=1,
                    p_ia_nonempty_writes=1,p_paired_ia_ports=1,p_allow_inactive_return_updates=1)),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def targeted_paths(module,pre,profile):
    for name,origin in register_origins(pre/"pre_lut.il").items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes",{})["fpga_register_origin"]=origin
    spare = max(bit for net in module["netnames"].values() for bit in net["bits"] if isinstance(bit,int))+1
    inputs = ["frame_accept","frame_request"] if profile=="ps" else ["i_ps_read_en","i_access_enable"]
    for name in inputs:
        for index,bit in enumerate(module["ports"][name]["bits"]):
            module["cells"][f"analysis_input_{name}_{index}"] = dict(type="FDRE",parameters={},
                attributes={},port_directions={"D":"input","Q":"output"},connections={"D":[spare],"Q":[bit]})
            spare+=1
    if profile=="ps":
        for index,bit in enumerate(module["ports"]["ram_read_en"]["bits"]):
            module["cells"][f"analysis_read_output_{index}"] = dict(type="FDRE",parameters={},
                attributes={},port_directions={"D":"input","Q":"output"},connections={"D":[bit],"Q":[spare]})
            spare+=1
    paths = {}
    targets = ["read_enable"] if profile=="ps" else ["capacity_fault","ram_enable"]
    for start in inputs:
        for end in targets:
            if profile=="ps":
                sink=lambda name,cell,port:name.startswith("analysis_read_output_")
            elif end=="capacity_fault":
                sink=lambda name,cell,port:"o_capacity_fault" in cell.get("attributes",{}).get("fpga_register_origin","")
            else:
                sink=lambda name,cell,port:"g_shared_bank" in name and port in ("ENARDEN","ENBWREN","WEA","WEBWE")
            result=connected_paths(module,limit=1,group_limit=1,
                root_filter=lambda name,cell,port,start=start:name.startswith("analysis_input_"+start+"_"),
                sink_filter=sink)
            if not result["graph_complete"]:
                raise RuntimeError("存储控制路径分析未完成")
            paths[start+"_to_"+end]=result
    return paths


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--reference",default=REFERENCE)
    parser.add_argument("--profiles",nargs="+",choices=PROFILES,default=list(PROFILES))
    parser.add_argument("--reuse-pre",action="store_true")
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    cases={};hashes={}
    for name in args.profiles:
        top,relative,parameters=PROFILES[name]
        for path in input_files(with_dependencies([ROOT/relative],ROOT),ROOT):
            hashes[str(path.relative_to(ROOT))]=digest(path)
        for variant in ("reference","candidate"):
            label=name+"_"+variant;snapshot=out/(label+".sv")
            text=(subprocess.check_output(["git","show",args.reference+":"+relative],cwd=ROOT,text=True)
                  if variant=="reference" else (ROOT/relative).read_text())
            if args.reuse_pre:
                if snapshot.read_text()!=text:raise RuntimeError("测量源码与已综合文件不一致："+label)
            else:snapshot.write_text(text)
            cases[label]=dict(top=top,configuration="完整部分和及共享存储读取控制测量",parameters=parameters,
                sources=list(map(str,with_dependencies([snapshot],ROOT))),
                options=["-DSYNTHESIS=1","-DXILINX_FPGA=1"]+[f"-G{k}={v}" for k,v in parameters.items()])
    config=out/"cases.json"
    if not args.reuse_pre:
        config.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+"\n")
        with(out/"prepare.log").open("w")as stream:
            subprocess.run([sys.executable,ROOT/"scripts/fpga/open_fpga_synth.py","--case-config",config,
                            "--cases",*cases,"--out",out/"pre","--through","pre_lut"],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    records={}
    for label,case in cases.items():
        pre,cost=out/"pre"/label,out/"cost"/label
        manifest=json.loads((pre/"manifest.json").read_text())
        for name,expected in manifest["sources_sha256"].items():
            if digest(ROOT/name)!=expected:raise RuntimeError("预映射依赖已改变："+name)
        with(out/(label+"_map.log")).open("w")as stream:
            subprocess.run([sys.executable,ROOT/"scripts/fpga/remap_fpga_luts.py","--source",pre,"--out",cost,
                            "--mode","physical-cost","--max-lut-inputs","8","--small-lut-area-cost","1",
                            "--wire-delay-ps","300","--delay-target-ps","6667","--discard-abc9-temporaries"],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        metrics=json.loads((cost/"metrics.json").read_text())
        module=json.loads((cost/"mapped.json").read_text())["modules"][case["top"]]
        paths=targeted_paths(module,pre,label.rsplit("_",1)[0])
        row=dict(parameters=case["parameters"],resources=metrics["resources"],
                 longest_register_path_cells=metrics["paths"]["longest_register_path_cells"],
                 paths=paths,mapped_sha256=digest(cost/"mapped.json"),pre_lut_sha256=digest(pre/"pre_lut.il"))
        records[label]=row
        print(json.dumps(dict(case=label,lut=row["resources"]["lut_sites_nominal_before_packing"],
                              maximum=row["longest_register_path_cells"],
                              paths={name:value["longest_register_path_cells"]for name,value in paths.items()})),flush=True)
    if hashes!={name:digest(ROOT/name)for name in hashes}:raise RuntimeError("测量期间 RTL 内容发生变化")
    report=dict(reference=args.reference,source_sha256=hashes,cases=records,
                mapping=dict(mode="physical-cost",max_lut_inputs=8,small_lut_area_cost=1,
                             wire_delay_ps=300,delay_target_ps=6667))
    (out/"measurement.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    main()
