# 完整 SoC RTL 与综合检查

## 当前版本

当前测量使用 R16 固定源码 `7c932a9e9ec5e48ab119f0227bb894763872157f`，导入起点为 GitHub 上游提交 `48f28649b274851a4768ee60ddb5c6c9e75de295`。完整源码摘要、功能结果、资源和组合路径保存在 [R16 测量目录](rtl_checkpoint_20261122_r16/README.md)。

完整 `soc_top` 包含 NPU、PicoRV32、256 KiB CPU RAM、AXI 互连和 UART。生产配置采用 16 × 16 阵列、64 位总线、8 个向量 PE、7 个 8,192 字节共享存储块、4,096 字节 im2col 缓存及 16 个 PS 帧。

目标器件为 `xc7a200tfbg484-3`，目标为 Vivado 总 Slice LUT 不超过 **50,000**、完整连接图中最长寄存器间组合路径不超过 **10 个组合单元**，并在 **150 MHz** 下满足建立时间和保持时间。

生产 RTL 使用可综合算术、布尔运算和数组描述硬件。LUT、BRAM 和 DSP 由综合工具推断；FPGA 门控采用 BUFGCE，通用门控采用低电平锁存使能结构。说明性 RTL 注释使用中文。

## 完整 SoC 开源综合

Yosys 与 ABC9 使用生产配置和完整 `soc_top` 完成综合。算术映射使用 RTL 的 `use_dsp` 属性，DSP 总预算为 740。连接图分析包含跨模块路径、同步存储的数据与控制输入，以及 DSP 的实际内部寄存器边界。

| 项目 | R16 结果 |
| --- | ---: |
| 逻辑 LUT | 48,701 |
| 分布式 RAM 的 LUT 位置 | 940 |
| SRL 的 LUT 位置 | 24 |
| 布局前 LUT 合计 | **49,665** |
| 触发器 | 42,203 |
| DSP | 713 |
| RAMB36 / RAMB18 | 164 / 66 |
| 最长寄存器间组合路径 | **13 级** |
| 超过 10 级的路径组 / 端点 | 126 / 1,026 |
| 连接图完整性 | 完整 |

布局前 LUT 合计低于 50,000。最长路径仍超过 10 级目标。本版本尚未执行 Vivado 布局布线，物理 Slice LUT 数量与 150 MHz 时序状态未确认。目标状态分别记录在 [status.json](rtl_checkpoint_20261122_r16/status.json) 中。

## 功能与算术验证

| 检查 | 结果 |
| --- | --- |
| 完整生产 NPU | 86 项任务、216,348 个 INT32 数值检查通过 |
| 帧输入位置与准备周期 | 1,860 项位置检查通过，每帧准备 11 个周期 |
| 完整 CPU 模式 0 | 6,272 个输出通过，49,272,702 个周期 |
| 完整 CPU 模式 1 | 6,272 个输出通过，2,781,063 个周期 |
| CPU 内存边界 | 两种模式的边界错误计数均为零 |
| 实际选中的 DSP 算术映射 | 379 个算术单元、94 组参数的组合等价检查通过 |

AXI 占用状态、PS 长度比较、调度器帧计数和 FIFO 释放选择分别保存形式证明、四态检查和数值任务的结果。各模块检查及完整构建输入见 [R16 验证说明](rtl_checkpoint_20261122_r16/README.md#功能与状态检查)。

## 重复运行

在仓库根目录执行完整 NPU 与开源综合：

```bash
python3 test/frame_address/run_npu.py --source-root . \
  --out build/r16_npu --verilator verilator --jobs 1

python3 scripts/fpga/open_fpga_synth.py --source-root . --cases soc_top \
  --out build/r16_soc --rtl-dsp-attributes --wide-alu-dsp-budget 740 \
  --max-register-path-cells 10 --require-register-path-limit
```

综合入口在完整路径超过 10 级时返回非零状态，同时保存全部已完成的综合和测量报告。

Vivado 板级综合与布局布线入口如下。首次克隆后先执行 `git submodule update --init picorv32`。

```bash
vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_fpga_150

VIVADO_RUN_IMPL=1 vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_fpga_150_impl
```

器件参数、实际引脚约束、资源报告及建立和保持时间检查见 [完整 SoC 器件测量](fpga_150mhz_measurement.md)。
