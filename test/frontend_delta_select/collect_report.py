#!/usr/bin/env python3
"""核对固定源码及已完成结果，生成接收步长选择的测量记录。"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/npu/conv/conv_im2col_frontend.sv"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    paths = {"formal": build / "formal/summary.json", "local": build / "local/summary.json",
             "segments": build / "local/delta_segments.json", "window": build / "window/summary.json"}
    rows = {name: json.loads(path.read_text()) for name, path in paths.items()}
    if not all(row["passed"] for row in rows.values()):
        raise RuntimeError("存在未完成的验证")
    current = sha(SOURCE)
    for name in ("formal", "local"):
        if rows[name]["source_sha256"] != current:
            raise RuntimeError("受测源码与当前文件不一致: " + name)
    formal, local, window = rows["formal"], rows["local"], rows["window"]
    if window["frontend_source_sha256"] != current or window["reference_frontend_sha256"] != formal["reference_sha256"]:
        raise RuntimeError("窗口模型的源码版本不一致")
    if not window["resident_stream_cycle_equivalent"] or not window["transaction_statistics_equivalent"]:
        raise RuntimeError("窗口输出比较未完成")
    if not local["state_formal"]["passed"] or not local["state_formal"]["state_process_unchanged"]:
        raise RuntimeError("实际状态过程检查未完成")
    if local["proof_sha256"] != sha(paths["formal"]) or window["arithmetic_proof_sha256"] != sha(paths["formal"]):
        raise RuntimeError("形式证明结果摘要不一致")
    for row in formal["cases"]:
        if not row["passed"] or row["inputs_constrained"]:
            raise RuntimeError("要求无约束输入的完整证明")
    measurements = {}
    for name, row in local["cases"].items():
        folder = Path(row["directory"])
        if sha(folder / "mapped.json") != row["mapped_sha256"] or sha(folder.parent / "pre_lut.il") != row["pre_lut_sha256"]:
            raise RuntimeError("已映射网络摘要不一致")
        if not row["abc9_equivalent"] or not all(path["graph_complete"] for path in row["paths"].values()):
            raise RuntimeError("映射等价或路径图检查未完成")
        measurements[name] = dict(resources=row["resources"],
            path_cells={key: value["longest_register_path_cells"] for key, value in row["paths"].items()},
            source_sha256=row["source_sha256"], mapped_sha256=row["mapped_sha256"],
            pre_lut_sha256=row["pre_lut_sha256"], max_lut_inputs=row["max_lut_inputs"],
            wire_delay_ps=row["wire_delay_ps"], abc9_equivalent=True, graph_complete=True)
    passes = [line for line in window["tests"] if line.startswith("WINDOW_DMA_PASS")]
    if len(passes) != 1:
        raise RuntimeError("窗口最终统计缺失")
    statistics = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", passes[0])}
    resident = next(line for line in window["tests"] if line.startswith("CASE consecutive_hits"))
    resident = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", resident)}
    report = dict(passed=True, reference_commit=formal["reference_commit"],
                  source_sha256=current, reference_sha256=formal["reference_sha256"],
                  production_files=[str(SOURCE.relative_to(ROOT))],
                  design=dict(delta_bits=32, carry_bits=1, q_equal_groups=2, select_inputs=5,
                              select_init="64'h00ac_acac_00ac_acac", new_registers=0, added_cycles=0),
                  formal=formal, actual_state_formal=local["state_formal"],
                  mapping=local["mapping"], parameters=local["parameters"], boundary=local["boundary"],
                  input_registers=local["input_registers"], local_measurements=measurements,
                  delta_segments={name: row["maximum_combinational_cells"] for name, row in rows["segments"]["cases"].items()},
                  window=dict(fpga=window["fpga"], reference_commit=window["reference_ref"],
                              statistics=statistics, resident=resident, resident_stream_records=window["resident_stream_cycles"],
                              resident_stream_sha256=window["resident_stream_sha256"],
                              resident_stream_cycle_equivalent=True, transaction_statistics_equivalent=True,
                              executable_sha256=window["executable_sha256"]),
                  common_sources=dict(dma_sha256=local["dma_sha256"], add_equal_sha256=local["add_equal_sha256"]),
                  artifacts={name: dict(path=str(path.relative_to(ROOT)), sha256=sha(path)) for name, path in paths.items()},
                  test_sha256={str(path.relative_to(ROOT)): sha(path) for path in sorted(Path(__file__).parent.glob("*.py"))})
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(passed=True, source_sha256=current, statistics=statistics, resident=resident), ensure_ascii=False))


if __name__ == "__main__":
    main()
