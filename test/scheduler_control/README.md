# 帧调度器候选选择

`ps_window_scheduler` 分别编码全部有效帧和游标之后的有效帧，然后选择本次命令使用的帧编号。有效帧的非零判断采用六输入平衡归并树；生产配置 `FRAME_COUNT=16` 使用两级 LUT 归并。

命令的接收、压力处理、完成、预测和帧进度更新均保持原有时钟边沿。该实现没有增加寄存器或准备周期。

## 完整模块资源

参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。参考源码为 `e6fd2b1f`。

| 映射方法 | 版本 | 逻辑 LUT | RAM LUT | FF | DSP | 最长寄存器路径 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 普通 Xilinx 映射 | 参考 | 1,296 | 108 | 892 | 2 | 13 |
| 普通 Xilinx 映射 | 当前 | 1,312 | 108 | 892 | 2 | 13 |
| 物理面积成本映射 | 参考 | 1,214 | 108 | 892 | 2 | 14 |
| 物理面积成本映射 | 当前 | 1,221 | 108 | 892 | 2 | 14 |

当前模块从 `opened`、`cursor` 或 `live` 寄存器发出的最长路径，在两种映射中分别为 11 级和 12 级。物理面积成本映射中，这些寄存器至 `command_buffer_valid` 和 `selected_id_valid` 的路径均为 10 级。

表中级数来自完整映射图的逐位寄存器边界分析，包含 LUT、进位、选择、异步存储读取和 DSP 内部寄存器边界。完整 SoC 的路径与物理 LUT 使用量由整机固定版本单独测量。器件时序以布线后的 6.667 ns 时钟检查为准。

## 验证

`run_formal.py` 包含 20 组非零判断证明，覆盖 1、2、3、6、7、16、31、36、37、64 位输入，以及通用逻辑和官方 `LUT6` 功能模型。

完整调度器的 10 组逐周期状态等价证明覆盖以下参数，每组分别使用通用逻辑和官方 FPGA 原语功能模型：

| SIZE | FRAME_COUNT | MAX_REUSE_TILES |
| ---: | ---: | ---: |
| 1 | 1 | 1 |
| 4 | 3 | 4 |
| 16 | 16 | 32 |
| 16 | 16 | 0 |
| 16 | 17 | 64 |

证明比较全部匹配的内部状态与公开输出，共 26,078 位，不限制输入取值或握手序列。组合 SAT 和时序归纳均已通过。

独立调度模型验证了 975 个任务、182,426 条命令及 167,577 个矩阵分块；其中包含切片、尾部帧、循环复用、存储压力和提前完成。检查包括 141,121 次预留数量判断、1,085,772 次银行容量判断，以及 4 种无效配置。所有 C++ 编译单元均启用未定义行为检查。

`measurement.json` 保存实际源码、证明、数值测试、映射网表和路径报告的 SHA-256，以及资源与路径统计。

## 复现

在仓库根目录执行以下命令。`PYTHONPATH` 指向提供 `pyosys` 的工具环境；综合和映射使用同一共享锁。

```sh
python3 test/scheduler_control/run_formal.py \
  --out build/scheduler_control/formal

python3 test/ps_compression/run_window_scheduler.py \
  --verilator /path/to/verilator \
  --out build/scheduler_control/numeric

python3 test/scheduler_control/prepare_measurement.py \
  --out build/scheduler_control/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/scheduler_control/inputs/cases.json \
  --cases scheduler_reference scheduler_current \
  --out build/scheduler_control/native \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/scheduler_control/native/scheduler_current \
  --out build/scheduler_control/physical/scheduler_current \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 test/scheduler_control/measure_paths.py \
  --mapped build/scheduler_control/physical/scheduler_current/mapped.json \
  --pre-lut build/scheduler_control/native/scheduler_current/pre_lut.il \
  --out build/scheduler_control/physical/scheduler_current/paths.json
```
