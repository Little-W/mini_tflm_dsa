#!/usr/bin/env python3
"""从模型定义补齐 DW 几何测试，双方使用相同随机张量和硬件量化条件。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from prepare import sha256
from prepare_conv import create_case


def geometry(record):
    return tuple(record[key] for key in ("input_h", "input_w", "input_channels", "output_h",
                                        "output_w", "output_channels", "stride_h", "stride_w",
                                        "kernel_h", "kernel_w", "pad_top", "pad_left"))


def node_geometry(node):
    shape, output, options = node["input_shapes"][0], node["output_shapes"][0], node["options"]
    if shape[0] != 1 or output[0] != 1 or options["depth_multiplier"] != 1:
        raise ValueError("DW 几何测试要求批量为 1、通道倍数为 1")
    if options["kernel_h"] != 3 or options["kernel_w"] != 3 or options["stride_h"] != options["stride_w"]:
        raise ValueError("该生成程序只支持 3×3 DW 与相同水平、垂直步长")
    if options["dilation_h_factor"] != 1 or options["dilation_w_factor"] != 1:
        raise ValueError("该生成程序只支持膨胀系数为 1 的 DW")
    stride = options["stride_h"]
    if options["padding"] == "SAME":
        top = max(0, (output[1] - 1) * stride + 3 - shape[1]) // 2
        left = max(0, (output[2] - 1) * stride + 3 - shape[2]) // 2
    elif options["padding"] == "VALID":
        top = left = 0
    else:
        raise ValueError("未知填充方式")
    if top != left or output[1] != (shape[1] + stride - 1) // stride or output[2] != (shape[2] + stride - 1) // stride:
        raise ValueError("模型输出形状无法使用当前共同算子生成程序表示")
    return (shape[1], shape[2], shape[3], output[1], output[2], output[3], stride, stride, 3, 3, top, left)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--existing-workloads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261121)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("输出目录已存在，请使用新的目录保留原始输入")
    shutil.copytree(args.existing_workloads, args.out)
    directory = args.out / "conv"
    catalogue = json.loads((directory / "workloads.json").read_text())
    by_geometry = {}
    for entry in catalogue["cases"]:
        record = json.loads((directory / entry["manifest"]).read_text())
        if record["operator"] == "depthwise":
            by_geometry[geometry(record)] = entry["name"]
    coverage = []
    added = []
    for path in sorted(args.prepared.glob("*/manifest.json")):
        model = json.loads(path.read_text())
        for node in model["graph"]["nodes"]:
            if node["op"] != "DEPTHWISE_CONV_2D":
                continue
            key = node_geometry(node)
            if key not in by_geometry:
                h, w, channels, _, _, _, stride, _, _, _, padding, _ = key
                name = f"model_dw3x3_s{stride}_{h}x{w}_c{channels}"
                record = create_case(directory, name, "depthwise", h, w, channels, channels, stride, padding, args.seed)
                if geometry(record) != key:
                    raise ValueError("生成的 DW 几何与模型节点不一致")
                entry = dict(name=name, operator="depthwise", manifest=name + "/case.json",
                             manifest_sha256=sha256((directory / name / "case.json").read_bytes()))
                catalogue["cases"].append(entry)
                added.append(name)
                by_geometry[key] = name
            coverage.append(dict(model=model["name"], node=node["index"], model_sha256=model["model"]["sha256"],
                                 workload=by_geometry[key], input_shape=node["input_shapes"][0],
                                 output_shape=node["output_shapes"][0], options=node["options"]))
    if not coverage:
        raise ValueError("参考模型中没有 DW 节点")
    (directory / "workloads.json").write_text(json.dumps(catalogue, indent=2) + "\n")
    report = dict(passed=True, model_depthwise_nodes=len(coverage),
                  unique_model_geometries=len({row["workload"] for row in coverage}), added_workloads=added,
                  purpose="使用模型几何与共同随机张量比较硬件执行时间；真实模型张量与逐通道量化另由完整模型测试覆盖",
                  coverage=coverage)
    (args.out / "model_dw_coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "coverage"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
