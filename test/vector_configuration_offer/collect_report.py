#!/usr/bin/env python3
"""核对形式证明、系统运行和候选源码，并生成统一结果文件。"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(text):
    return re.sub(r"\s+","",re.sub(r"//[^\n]*|/\*.*?\*/","",text,flags=re.S))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build",type=Path,required=True)
    parser.add_argument("--candidate",type=Path,required=True)
    parser.add_argument("--out",type=Path,default=HERE/"measurement.json")
    args=parser.parse_args()
    build=args.build.resolve()
    formal=json.loads((build/"formal/summary.json").read_text())
    system=json.loads((build/"system/summary.json").read_text())
    if not formal["passed"] or not system["passed"]:
        raise RuntimeError("验证尚未完成")
    merged=dict(formal["source_sha256"])
    for name,value in system["build"]["source_sha256"].items():
        if name in merged and merged[name]!=value:
            raise RuntimeError("两项检查使用了不同源码: "+name)
        merged[name]=value
    for name,value in merged.items():
        if digest(ROOT/name)!=value:
            raise RuntimeError("源码已发生变化: "+name)
    reference=ROOT/"rtl/npu/conv/vector_engine.sv"
    candidate=args.candidate.resolve()
    current="dma_cfg_valid = state==CONFIGURE;"
    previous="dma_cfg_valid = state==CONFIGURE && dma_cfg_ready;"
    proposed=reference.read_text().replace(previous,current)
    if candidate.read_text().count(current)!=1 or tokens(proposed)!=tokens(candidate.read_text()):
        raise RuntimeError("候选包含配置有效表达式之外的语义修改")
    for run in system["runs"]:
        if not run["passed"] or run["statistics"]["clients"]!="15":
            raise RuntimeError("客户端覆盖不完整")
    files=[p for p in HERE.iterdir() if p.suffix in (".py",".sv",".cpp",".md")]
    result={
        "passed":True,
        "source_revision":formal["source_revision"],
        "proposal":{
            "reference_assignment":previous,"candidate_assignment":current,
            "reference_vector_sha256":digest(reference),
            "single_assignment_candidate_sha256":hashlib.sha256(proposed.encode()).hexdigest(),
            "reviewed_candidate_sha256":digest(candidate),
            "candidate_tokens_match_proposal":True,
            "candidate_comment":"配置等待期间持续提供描述符，接收边沿由就绪信号决定。"},
        "conclusion":"配置等待期间持续提供描述符保持配置接受与任务完成行为，可移除 ready 到 valid 的组合依赖。",
        "proof_scope":{
            "vector":"生产向量单元的实际控制寄存器和配置载荷，无外部输入假设的一步归纳证明。",
            "consumers":"实际仲裁及 DMA 配置使用者；CONFIGURE 的全部客户端请求为零时，对全部其余状态和输入取值证明接受事件及授权状态相同。",
            "top_mutual_exclusion":"实际完整 NPU 运行中，对整个 run_vector 周期执行普通客户端请求互斥断言；矩阵、向量交替任务和错误恢复均覆盖。"},
        "formal":formal,
        "system":system,
        "validated_source_sha256":merged,
        "test_source_sha256":{str(p.relative_to(ROOT)):digest(p) for p in sorted(files)},
        "report_inputs_sha256":{str(p.relative_to(build)):digest(p) for p in (
            build/"formal/summary.json",build/"system/summary.json")}}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed":True,"report":str(args.out),"sha256":digest(args.out)},ensure_ascii=False))


if __name__=="__main__":
    main()
