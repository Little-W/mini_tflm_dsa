# 顶层故障与 DMA 中止组合

`npu_top` 先合并两个容量故障与帧错误，使用一个六输入 LUT 生成公共条件。末级 `LUT6_2` 直接接收该条件、`run_conv`、`run_vector`、`conv_error`、`dma_bus_error` 和 `abort_pending`。

末级初始化值为 `64'hffff_ffff_ffff_feaa`。`O5` 生成当前任务故障，`O6` 生成 DMA 仲裁器的中止输入：

```systemverilog
task_fault = capacity_or_frame_fault || dma_bus_error ||
             ((run_conv || run_vector) && conv_error);
arbiter_abort = task_fault || abort_pending;
```

`O5` 使用低 32 位真值表；`O6` 在 `abort_pending=0` 时复用同一真值表，在 `abort_pending=1` 时输出一。组合保持同周期生效，生产 RTL 没有增加状态或采样边沿。`ASIC_SYNTHESIS` 使用通用表达式，并优先于其余两个宏。

## 形式证明和数值比较

参考提交为 `47e51eff9831b42a36326cec6e074245ba0805d2`。测试每次读取实际新旧 `npu_top.sv`，从 `ps_capacity_fault` 声明到 `controller_done_valid` 声明之间提取完整故障组合，并从实际 `u_block_dma_arbiter` 实例提取 `.abort` 表达式。

输入共 11 位，包括两个容量故障、DMA 错误、帧模式、帧完成、两位帧错误码、两个执行模式、卷积错误和中止状态。全部输入相互独立，未添加取值或握手假设。

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| SAT 等价证明 | `XILINX_FPGA`、`SYNTHESIS`、`ASIC_SYNTHESIS` 的全部 8 种宏组合 | 通过 |
| 宏选择检查 | 每种宏组合的实际 `p_fault_use_lut` 常量 | 通过 |
| 官方原语数值比较 | 每种宏组合穷举 2,048 组输入，共 16,384 组 | 通过 |
| 映射后真值比较 | 新旧设计、两种映射，每种穷举 2,048 组输入，共 8,192 组 | 通过 |
| 原语真值表检查 | `O5` 的全部 32 项及 `O6` 的两个 32 项区域 | 通过 |

形式证明与数值仿真使用 [Xilinx Unisim 的 `LUT6_2` 源文件](https://github.com/Xilinx/XilinxUnisimLibrary/blob/master/verilog/src/unisims/LUT6_2.v)。模型及 Apache-2.0 许可证保存在 `vendor/`；模型 SHA-256、提取代码、参考真值表和日志摘要保存在 [measurement.json](measurement.json)。

## 局部面积与路径

测量为完整故障组合设置 11 个输入寄存器和两个输出寄存器。这 13 个寄存器仅定义测量边界。两种设计使用相同边界、原语库与综合选项；物理成本映射采用与 R19 相同的 6,667 ps 延迟目标、300 ps 连线成本、最多八输入 LUT 和默认小型 LUT 面积成本。

| 指标 | 原生参考 | 原生当前 | 物理成本参考 | 物理成本当前 |
| --- | ---: | ---: | ---: | ---: |
| 映射 LUT 原语数 | 4 | 2 | 3 | 2 |
| 测量寄存器数 | 13 | 13 | 13 | 13 |
| 最长组合级数 | 2 | 2 | 3 | 2 |
| `dma_bus_error` 至 `task_fault` | 2 | 1 | 2 | 1 |
| `dma_bus_error` 至仲裁器 `abort` | 2 | 1 | 3 | 1 |
| 容量输入至 `task_fault` | 2 | 2 | 2 | 2 |
| 容量输入至仲裁器 `abort` | 2 | 2 | 3 | 2 |
| 帧输入至 `task_fault` | 2 | 2 | 1 | 2 |
| 帧输入至仲裁器 `abort` | 2 | 2 | 2 | 2 |
| 卷积输入至 `task_fault` | 1 | 1 | 2 | 1 |
| 卷积输入至仲裁器 `abort` | 1 | 1 | 3 | 1 |
| `abort_pending` 至仲裁器 `abort` | 1 | 1 | 1 | 1 |

容量输入包括 `ps_capacity_fault` 和 `shared_ram_capacity_fault`。帧输入包括 `frame_mode_q`、`inner_done_valid` 和 `inner_err_code` 的两个位。卷积输入包括 `run_conv`、`run_vector` 和 `conv_error`。`task_fault` 与 `abort_pending` 无组合依赖。

两种当前映射均为一个 `LUT6` 和一个 `LUT6_2`。全部仲裁器中止路径、以及每个输入到两个输出的最大级数均未增加。物理成本映射中，帧输入至 `task_fault` 为两级，至 `abort` 也为两级；表格分别保留这两个输出的比较结果。报告保存全部 22 个输入输出组合的实际连接路径。

这些结果描述局部结构级数和映射资源。完整 NPU 功能回归与整机时序测量使用合并后的固定源码执行。

## 运行方法

```sh
python3 test/npu_fault_fanin/run_formal.py \
  --out build/npu_fault_fanin/formal
python3 test/npu_fault_fanin/prepare_measurement.py \
  --out build/npu_fault_fanin/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/npu_fault_fanin/inputs/cases.json \
  --cases reference current --out build/npu_fault_fanin/native \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
for name in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "build/npu_fault_fanin/native/$name" \
    --out "build/npu_fault_fanin/cost/$name" --mode physical-cost \
    --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
done
python3 test/npu_fault_fanin/collect_report.py --results build/npu_fault_fanin
```
