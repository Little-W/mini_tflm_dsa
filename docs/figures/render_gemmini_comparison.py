#!/usr/bin/env python3
"""Render cycle measurements from the verified Gemmini comparison data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=here.parent / "gemmini_measurements.json")
    parser.add_argument("--out", type=Path, default=here / "gemmini_comparison")
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    font = args.font or Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({"font.size": 10.5, "axes.unicode_minus": False,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#c9d1d9", "text.color": "#1f2937",
                         "axes.labelcolor": "#334155", "xtick.color": "#334155",
                         "ytick.color": "#334155", "svg.fonttype": "path",
                         "svg.hashsalt": "gemmini-comparison"})
    data = json.loads(args.data.read_text())
    models = {m["model"]: m for m in data["models"]}
    order = ["mnist_cnn", "mobilenet_v1_vww", "resnet8_cifar10", "ds_cnn_kws"]
    labels = ["MNIST CNN", "MobileNetV1\nVWW", "ResNet-8\nCIFAR-10", "DS-CNN\nKWS"]
    original = [models[k]["original"]["software_speedup"] for k in order]
    current = [models[k]["modified"]["software_speedup"] for k in order]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.8), gridspec_kw={"width_ratios": [1, 1.04]})
    fig.subplots_adjust(left=0.06, right=0.98, top=0.80, bottom=0.28, wspace=0.30)
    fig.suptitle("Gemmini 对等测试与完整模型性能", x=0.06, y=0.98,
                 ha="left", fontsize=20, weight="bold")
    aggregate = data["aggregate_invoke"]["modified_software_speedup"]
    configurations = len(data["operator_totals"])
    fig.text(0.06, 0.895, f"完整模型 Invoke 合计 {aggregate:,.2f}×  ·  34 个共同算子  ·  Gemmini {configurations} 种固定配置",
             fontsize=11.5, color="#475569")

    ax = axes[0]
    pos = np.arange(len(order))
    width = 0.34
    b0 = ax.bar(pos - width / 2, original, width, color="#a8b4c2", label="原始硬件")
    b1 = ax.bar(pos + width / 2, current, width, color="#007f7b", label="当前硬件")
    ax.axhline(1000, color="#a15c2e", linestyle=(0, (4, 3)), linewidth=1.1, zorder=0)
    ax.text(-0.43, 1050, "1000×", color="#a15c2e", fontsize=9)
    ax.set_title("完整 Invoke 的软件加速比", loc="left", pad=13, weight="bold")
    ax.set_ylabel("软件周期 / 硬件周期")
    ax.set_xticks(pos, labels)
    upper = np.ceil(max(1100, max(current) * 1.16) / 500) * 500
    ax.set_ylim(0, upper)
    ax.set_yticks(np.arange(0, upper + 1, 500))
    ax.yaxis.grid(True, color="#e7ecf1", linewidth=0.7)
    ax.set_axisbelow(True)
    for bars in (b0, b1):
        ax.bar_label(bars, labels=[f"{r.get_height():,.1f}×" for r in bars],
                     padding=4, fontsize=9)
    ax.legend(loc="upper left", frameon=False, fontsize=9.5)

    ax = axes[1]
    total = {r["gemmini_profile"]: r for r in data["operator_totals"]}
    series = [
        ("当前 NPU", "#007f7b", [total["sp64_acc16"]["gemm_npu_cycles"], total["sp64_acc16"]["conv_npu_cycles"]]),
        ("Gemmini 64+16 KiB", "#244b76", [total["sp64_acc16"]["gemm_gemmini_cycles"], total["sp64_acc16"]["conv_gemmini_cycles"]]),
        ("Gemmini 32+32 KiB", "#5489b5", [total["sp32_acc32"]["gemm_gemmini_cycles"], total["sp32_acc32"]["conv_gemmini_cycles"]]),
        ("Gemmini 256+64 KiB", "#9db5cb", [total["sp256_acc64"]["gemm_gemmini_cycles"], total["sp256_acc64"]["conv_gemmini_cycles"]]),
    ]
    if "sp256_acc64_dma128" in total:
        extra = total["sp256_acc64_dma128"]
        series.append(("Gemmini 256+64 KiB，DMA128", "#b97932",
                       [extra["gemm_gemmini_cycles"], extra["conv_gemmini_cycles"]]))
    positions = np.array([1.2, 0.0])
    height = 0.76 / len(series)
    for i, (name, color, values) in enumerate(series):
        bars = ax.barh(positions + ((len(series)-1)/2 - i) * height, np.array(values) / 1e6,
                       height * 0.87, color=color, label=name)
        ax.bar_label(bars, labels=[f"{v:,}" for v in values], padding=4, fontsize=9)
    ax.set_title("共同算子总周期，数值越小越快", loc="left", pad=13, weight="bold")
    ax.set_yticks(positions, ["31 个\nGEMM", "3 个\nConv/DW"])
    maximum = max(max(values) for _, _, values in series) / 1e6
    ax.set_xlim(0, np.ceil(maximum * 1.22 * 10) / 10)
    ax.set_xlabel("百万周期")
    ax.xaxis.grid(True, color="#e7ecf1", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.50, -0.18), ncols=2,
              frameon=False, fontsize=9.2, handlelength=1.6, columnspacing=1.2)
    fig.text(0.06, 0.08, "整网：PicoRV32 + TFLM，batch 1，两个输入均值；初始化单独统计。", fontsize=9.5, color="#475569")
    fig.text(0.06, 0.04, "共同算子：16×16 阵列，32 位 AXI，相同读写服务；GEMM 布局转换在计时外；Gemmini 未标注项为 DMA64。", fontsize=9.5, color="#475569")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out.with_suffix(".png"), dpi=190, facecolor="white")
    svg = args.out.with_suffix(".svg")
    fig.savefig(svg, facecolor="white", metadata={"Date": None})
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    plt.close(fig)
    print(args.out.with_suffix(".png"))


if __name__ == "__main__":
    main()
