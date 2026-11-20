#!/usr/bin/env python3
"""汇总同源前端、队列形式证明、映射及 FPGA 窗口比较结果。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = "rtl/npu/conv/conv_im2col_frontend.sv"
QUEUE = "rtl/npu/dma/conv_window_queue.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path):
    path = path.resolve()
    return dict(path=str(path), sha256=digest(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("frontend-proof", "queue-proof", "local", "queue-map", "window", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("frontend_proof", "queue_proof", "local", "queue_map", "window")}
    data = {name: json.loads(path.read_text()) for name, path in paths.items()}
    if not all(value["passed"] for value in data.values()):
        raise RuntimeError("Every verification and measurement must complete")
    frontend_sha, queue_sha = digest(ROOT / FRONTEND), digest(ROOT / QUEUE)
    if data["frontend_proof"]["source_sha256"] != frontend_sha or data["local"]["source_sha256"] != frontend_sha:
        raise RuntimeError("Frontend source differs from the compared source")
    if data["queue_proof"]["source_sha256"] != queue_sha or data["queue_map"]["source_sha256"] != queue_sha:
        raise RuntimeError("Queue source differs from the compared source")
    window = data["window"]
    if window["frontend_source_sha256"] != frontend_sha or window["queue_source_sha256"] != queue_sha:
        raise RuntimeError("The FPGA model uses different RTL")
    reference = data["frontend_proof"]["reference_commit"]
    if any(data[name]["reference_commit"] != reference for name in ("queue_proof", "local", "queue_map")):
        raise RuntimeError("Reference revisions differ")
    if window["reference_ref"] != reference or not window["resident_stream_cycle_equivalent"]:
        raise RuntimeError("The window comparison must use the fixed reference")
    local_cases = {}
    queue_cases = {}
    for label in ("reference", "current"):
        measured = data["local"]["cases"][label]
        local_cases[label] = dict(resources=measured["resources"],
            depths={name: value["longest_register_path_cells"] for name, value in measured["paths"].items()},
            graph_complete=all(value["graph_complete"] for value in measured["paths"].values()),
            source_sha256=measured["source_sha256"], mapped_sha256=measured["mapped_sha256"],
            pre_lut_sha256=measured["pre_lut_sha256"], log_sha256=measured["log_sha256"])
        queue = data["queue_map"]["cases"][label]
        queue_cases[label] = dict(resources=queue["metrics"]["resources"],
            longest_register_path_cells=queue["metrics"]["paths"]["longest_register_path_cells"],
            graph_complete=queue["metrics"]["paths"]["graph_complete"],
            metrics_sha256=queue["metrics_sha256"])
    report = dict(passed=True, reference_commit=reference,
        source_sha256={FRONTEND: frontend_sha, QUEUE: queue_sha},
        reference_sha256={FRONTEND: data["frontend_proof"]["reference_sha256"],
                          QUEUE: data["queue_proof"]["reference_sha256"]},
        frontend_formal=data["frontend_proof"], queue_formal=data["queue_proof"],
        local_mapping=dict(scope=data["local"]["boundary"], RW=5, CACHE_POLICY=3,
                           actual_dma_field_selection=True, cases=local_cases),
        queue_mapping=dict(configuration=data["queue_map"]["configuration"], cases=queue_cases),
        window=dict(fpga=window["fpga"], configuration=dict(BUS_WIDTH=32, LANES=4, IM2COL_SIZE=16,
                    WINDOW_OUTSTANDING=4, CONV_CACHE_SETS=128, CONV_CACHE_POLICY=3),
                    tests=window["tests"], resident_stream_cycle_equivalent=True,
                    resident_stream_cycles=window["resident_stream_cycles"],
                    resident_stream_sha256=window["resident_stream_sha256"],
                    executable_sha256=window["executable_sha256"],
                    reference_executable_sha256=window["reference"]["executable_sha256"]),
        artifacts={name: artifact(path) for name, path in paths.items()},
        test_source_sha256={str(path.relative_to(ROOT)): digest(path)
                           for path in sorted(Path(__file__).parent.glob("*.py"))})
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("FRONTEND_TILE_INPUT_REPORT_PASS", str(args.out), flush=True)


if __name__ == "__main__":
    main()
