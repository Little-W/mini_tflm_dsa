#!/usr/bin/env python3
"""根据逐项整数检查结果绘制 DW 性能比较图。"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "dw_shared_quant_20261121"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DATA / "operator_targets.json")
    parser.add_argument("--output", type=Path, default=HERE / "dw_shared_quant_20261121")
    args = parser.parse_args()
    report = json.loads(args.input.read_text())
    rows = [item for item in report["operators"]["items"] if item["operation"] == "depthwise"]
    if not rows or any(6 * row["npu_cycles"] > 5 * row["gemmini_cycles"] for row in rows):
        raise ValueError("The input must contain passing DW comparisons")

    # 使用可用的中文字体，保证轴标题和图注能够正常显示。
    font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if font_path.exists():
        font_manager.fontManager.addfont(str(font_path))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=font_path).get_name()
    plt.rcParams.update({"font.size": 10, "axes.unicode_minus": False, "svg.fonttype": "path"})
    labels = []
    ratios = []
    for row in rows:
        shape = row["shape"]
        labels.append(
            f'{shape["input_h"]}×{shape["input_w"]} · C{shape["input_channels"]} · stride {shape["stride"]}'
        )
        ratios.append(row["gemmini_cycles"] / row["npu_cycles"])

    fig, ax = plt.subplots(figsize=(9.8, 6.7))
    fig.subplots_adjust(left=0.28, right=0.96, top=0.87, bottom=0.18)
    colors = ["#c57a24" if value == min(ratios) else "#286a91" for value in ratios]
    ax.barh(range(len(rows)), ratios, height=0.62, color=colors)
    ax.set_yticks(range(len(rows)), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max(ratios) + 0.36)
    ax.axvline(1.2, color="#4b5563", linestyle="--", linewidth=1.2, label="要求：1.2×")
    for index, value in enumerate(ratios):
        ax.text(value + 0.035, index, f"{value:.4f}×", va="center", fontsize=10)
    ax.set_xlabel("加速比：Gemmini 周期 / NPU 周期")
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, pad=8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#cbd5e1")
    ax.legend(loc="lower right", frameon=False)
    fig.suptitle("DW 与 Gemmini DW 专用实现的逐项比较", x=0.5, y=0.965, fontsize=16)
    fig.text(0.5, 0.91, f"{len(rows)}/{len(rows)} 项通过；NPU 使用 16 路 DW PE 与共享 16 路量化", ha="center", fontsize=11)
    fig.text(0.5, 0.075, "AXI64 · 首拍最早 8 周期 · 80 KiB 逻辑状态上限 · 相同时钟频率", ha="center", fontsize=10)
    fig.text(0.5, 0.035, "包含冷数据传输、计算、量化和写回；Gemmini 采用较短的有效实测区间", ha="center", fontsize=9, color="#475569")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg", "pdf"):
        fig.savefig(args.output.with_suffix("." + extension), dpi=180, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
