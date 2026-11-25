# 权重加载器行反馈与列坐标验证

`kernel_loader` 将完整行数据与行结束标志在同一时钟边沿保存。下一周期的列更新共同选择已保存数据与零反馈，保持权重缓冲器的写入时刻和存储容量。完整宽度的列坐标先并行压缩三个操作数，再使用四位分组的前缀加法器；候选字段比较保留三位比较结果及第一层归并结果。

参考提交为 `f468ca5dd6c7de74c83c7c77d4cf4d09b410cd32`。形式证明和周期比较分别装载参考提交的全部依赖，并重新命名其模块定义。参考实例与当前实例具有独立的内部实现。

## 完整模块综合

参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`DMA_LANES=8`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=1`，全部公开端口参与综合。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 4,543 | 4,336 |
| 触发器 | 2,338 | 2,339 |
| RAMB18 | 16 | 16 |
| DSP48 | 0 | 0 |
| 寄存器之间最长组合逻辑级数 | 11 | 10 |

工具为 Yosys `0.71+40`、`read_slang` 与 `synth_xilinx` 的 ABC9 映射。两个实现使用相同的综合设置与 20 份固定源码，只有 `kernel_loader.sv` 和 `kernel_candidate_equal.sv` 的内容不同。当前最长路径从 `u_ctrl.load_col_in_group` 到 `comparison_match_q`，完整单元连接图中没有未分类单元。150 MHz 对应的实际器件时序仍需布局布线延迟分析。

## 功能与周期比较

| 检查 | 已完成结果 |
| --- | --- |
| 完整模块无限时序等价 | 5 组参数，54,355 位全部通过，公开输入不增加约束 |
| 生产参数四态比较 | 20,004 周期，每周期检查 23 个公开输出 |
| 异步复位四态比较 | 4,004 周期，复位覆盖 `0/1/X/Z`，检查相同 23 个输出 |
| 通用通道数四态比较 | `DMA_LANES=3` 和 `DMA_LANES=1` 各 4,036 周期，额外检查行累积数据 |
| 完整事务逐周期比较 | 29,439 个比较周期，23 个输出全部一致 |
| 数值与吞吐检查 | 285 个 tile、72,960 个值、312 次 DMA、1,649 个收发重叠周期全部一致 |

事务测试包含 S8/S16、im2col、尾部补零、预取命中、预取丢弃及清空操作，并启用 C++ 未定义行为检查。形式参数还覆盖 128 位总线、32 位计数、非二次幂通道数和单通道情况。

通用分支测试向有效位、列号和数据注入未知值及高阻态，并逐周期比较内部行累积数据。`last_ext_beat` 在组合过程开始时赋零，仅由成立的条件置一，公开输入中的未知值保留该条件过程的四态行为。专项测试同时检查该标志始终为确定值，以及非零行数据和行结束事件均实际发生。

## 复现

在仓库根目录运行。`kernel_verilator` 指向已配置 C++20 编译环境的 Verilator 可执行文件；其他工具为 `python`、`iverilog`、`vvp` 和包含 `read_slang` 的 `pyosys`。

```sh
kernel_result=/tmp/kernel_row_feedback
kernel_verilator=verilator

python test/kernel_row_feedback/run_formal.py \
  --out "$kernel_result/formal"

python test/kernel_prefetch/run_loader_four_state.py \
  --reference f468ca5d --count-width 29 \
  --out "$kernel_result/four_state"

python test/kernel_row_feedback/check_reset_four_state.py \
  --prepared "$kernel_result/four_state" \
  --out "$kernel_result/reset_four_state"

python test/kernel_row_feedback/check_general_four_state.py \
  --prepared "$kernel_result/four_state" \
  --out "$kernel_result/general_four_state"

python test/kernel_prefetch/run_reference_comparison.py \
  --reference f468ca5d --bus-width 64 --count-width 29 \
  --verilator "$kernel_verilator" \
  --out "$kernel_result/transactions"

python test/kernel_row_feedback/prepare_measurement.py \
  --out "$kernel_result/inputs"

for kernel_variant in reference current; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root "$kernel_result/inputs/$kernel_variant" \
    --case-config "$kernel_result/inputs/cases.json" \
    --cases "$kernel_variant" \
    --out "$kernel_result/synthesis" \
    --lock-file "$kernel_result/synthesis.lock"
done
```

各项检查写入 `summary.json`；综合写入每个实现的 `metrics.json`、`manifest.json` 和阶段脚本。输入副本的 `source_sha256.json` 记录所有源码内容的 SHA-256。
