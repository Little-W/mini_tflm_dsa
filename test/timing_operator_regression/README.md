# 62 项算子数值与周期回归

`run.py` 使用相同输入张量、AXI 存储模型与硬件参数，运行 36 项共同算子和 26 项补充数值算子。比较时逐项检查结果摘要和完成周期，任一算子增加周期都会返回失败。

当前 SoC 配置使用 `run_production.py`，其中 NPU 地址宽度为 32、矩阵维度计数宽度为 29，并显式检查矩阵两路和向量一路量化参数。运行方法与参数表见 [当前 SoC 配置回归](README_production.md)。

## 固定测试配置

| 项目 | 配置 |
| --- | --- |
| 阵列尺寸 | 16 × 16 |
| NPU 地址宽度、矩阵维度计数宽度 | 19、16 |
| 矩阵输出量化、向量独立量化并行度 | 2、1 |
| `PS_STORAGE_ROWS` 参数 | 0 |
| AXI 数据宽度 | 64 位 |
| 共享存储 | 7 个存储体，每个 8192 字节 |
| im2col 缓存 | 4096 字节，128 字节缓存行，16 组，2 路 |
| 向量 PE | 8 |
| 部分和存储 | 49152 字节，16 帧 |
| 最大 DMA 请求 | 2048 字节 |
| AXI 首次读取响应 | 8 个周期 |
| AXI 连续读取 | 每周期 1 拍 |
| 仿真宏 | `SYNTHESIS`、`XILINX_FPGA` |
| 共同算子随机种子 | `20261116` |
| 补充算子随机种子 | `20261123` |

共同算子的形状与张量 SHA-256 来自 `test/gemmini_comparison/public_operator_reference_20261123.json`。补充集合包括带非零量化偏移的 GEMM、卷积及深度卷积。测试同时检查数值结果和完整外部存储镜像。

## 运行方法

需要 Python 3、NumPy、Verilator 和支持 C++20 的 C++ 编译器。运行目录可以位于仓库外，输出文件包含生成的输入、编译产物、逐项日志及 JSON 结果。

首先为原始提交建立独立工作目录，并运行原始版本：

```sh
git worktree add --detach ../rtl_reference 2247144937c2fd04039b9b005151f371d6b51f8f
git -C ../rtl_reference submodule update --init --recursive
python test/timing_operator_regression/run.py \
  --repo ../rtl_reference \
  --out ../measurements/reference \
  --jobs 1
```

再使用已保存的输入和存储模型运行修改版本，并逐项比较：

```sh
python test/timing_operator_regression/run.py \
  --repo . \
  --out ../measurements/current \
  --inputs-from ../measurements/reference/inputs \
  --compare-with ../measurements/reference/all_cases.json \
  --jobs 1
```

两次运行分别编译对应工作目录的 RTL。同一次运行的两个算子集合使用同一个可执行文件。`--verilator` 可以指定 Verilator 的完整路径。

只生成和检查输入时，使用 `--prepare-only`。汇总已有完整运行目录时，使用 `--collect-only` 并指定原有 `--inputs-from`。输入描述文件保存种子、张量摘要、存储模型来源和文件摘要；已有输入发生变化时，检查会返回失败。

## 结果文件

- `inputs/input_manifest.json`：62 项输入及存储模型的 SHA-256。
- `collections/common36`、`collections/numeric26`：分组数值检查、编译信息与硬件配置。
- `all_cases.json`：全部算子的完成周期、输出摘要、源文件摘要和 AXI 事件时刻。
- `comparison.json`：逐项周期差、输出一致性、配置一致性和输入一致性。

`comparison.json` 中的 `passed` 要求两次运行完成同一组 62 项测试、硬件配置相同、输入描述文件摘要相同、全部输出相同，并且每一项修改版本的周期数都不超过原始版本。

## 原始版本实测

原始提交 `2247144937c2fd04039b9b005151f371d6b51f8f` 的 62 项数值检查全部通过。保存的 `reference_22471449.json` 包含逐项周期、输入与输出摘要以及测试配置。

| 集合 | GEMM 数量 | 卷积及深度卷积数量 | GEMM 周期之和 | 卷积及深度卷积周期之和 | 总周期 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 共同算子 | 31 | 5 | 240714 | 150389 | 391103 |
| 补充数值算子 | 20 | 6 | 163294 | 26992 | 190286 |
| 合计 | 51 | 11 | 404008 | 177381 | 581389 |

测试输入和编译产物由脚本生成，不需要加入版本管理。
