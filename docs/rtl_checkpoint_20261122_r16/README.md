# R16 完整 SoC 验证与综合结果

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

本版本以 GitHub 上游提交 `48f28649b274851a4768ee60ddb5c6c9e75de295` 为导入起点。功能与综合使用固定源码 `7c932a9e9ec5e48ab119f0227bb894763872157f`，其 RTL、配置和验证输入的 SHA-256 保存在 `source_hashes.json`。报告更新不改变这份被测 RTL。

## 生产配置与实现

目标器件为 `xc7a200tfbg484-3`。完整 `soc_top` 包含 16 × 16 计算阵列、8 个向量 PE、64 位 AXI、7 个 8,192 字节共享存储块、4,096 字节 im2col 缓存、16 个 PS 帧、完整 PicoRV32 和 256 KiB CPU RAM。配置来自 `config/npu_fpga.mk`。

生产 RTL 使用可综合算术、比较、选择和数组描述硬件，LUT、BRAM 和 DSP 由综合工具推断。代码修改使用 `rtl-design`、`synthesizable-rtl-style`，新增说明性注释使用中文。开源综合根据 RTL 的 `use_dsp` 属性映射算术，DSP 总预算为 740；实际选中的 379 个算术单元覆盖 94 组参数，全部组合等价检查通过。

## 完整 SoC 测量

| 项目 | 结果 |
| --- | ---: |
| 逻辑 LUT | 48,701 |
| 分布式 RAM 的 LUT 位置 | 940 |
| SRL 的 LUT 位置 | 24 |
| 布局前 LUT 合计 | **49,665** |
| 触发器 | 42,203 |
| DSP | 713 |
| RAMB36 / RAMB18 | 164 / 66 |
| 最长寄存器间组合路径 | **13 级** |
| 超过 10 级的路径组 | 126 |
| 超过 10 级的端点 | 1,026 |
| 连接图 | 完整 |

布局前 LUT 合计低于 50,000。最长路径仍超过 10 级目标。组合路径统计包含同步存储的数据、使能和控制输入，以及 DSP 的实际内部寄存器边界。全部连接路径的深度分布保存在 `soc_paths.json`，展示路径按 500 条路径、1,000 组和最小 11 级生成。

本版本尚未执行 Vivado 布局布线，物理 Slice LUT 数量与 150 MHz 建立、保持时间状态未确认。完整运行入口见 [器件测量说明](../fpga_150mhz_measurement.md)。

## 功能与状态检查

| 检查 | 结果 |
| --- | --- |
| 完整 NPU | 86 项任务、216,348 个 INT32 检查通过 |
| 帧输入位置与准备周期 | 1,860 项位置检查通过，每帧准备 11 个周期 |
| CPU 模式 0 | 6,272 个输出通过，49,272,702 个周期 |
| CPU 模式 1 | 6,272 个输出通过，2,781,063 个周期 |
| CPU 数值及内存边界 | 两模式的差异与边界错误计数均为零 |
| AXI 双项占用状态 | 9 种位宽形式证明、1,800,009 次四态比较通过 |
| PS 长度比较 | 5 组形式证明、249,994 次四态比较、120,368 个 INT32 检查通过 |
| scheduler 帧计数 | 666,384 次四态比较、975 个调度用例通过 |
| FIFO 释放选择 | 21 组形式证明、1,849,100 次四态比较、两种总线共 162 项数值任务通过 |

上述模块结果分别位于 `test/axi_occupancy`、`test/ps_length_comparison`、`test/scheduler_opened_boundary` 和 `test/fifo_release_selection`。NPU 与 CPU 的完整参数和数值结果保存在本目录的对应 JSON 文件中。

## 重复运行

在仓库根目录执行：

```bash
python3 test/frame_address/run_npu.py --source-root . \
  --out build/r16_npu --verilator verilator --jobs 1
python3 scripts/fpga/open_fpga_synth.py --source-root . --cases soc_top \
  --out build/r16_soc \
  --max-register-path-cells 10 --require-register-path-limit
python3 scripts/fpga/netlist_metrics.py build/r16_soc/soc_top/mapped.json \
  --top soc_top --out build/r16_soc/soc_paths.json \
  --register-origins build/r16_soc/soc_top/pre_lut.il \
  --path-limit 500 --group-limit 1000 --minimum-path-cells 11 \
  --max-register-path-cells 10
python3 scripts/fpga/test_wide_alu_dsp.py --out build/r16_dsp_formal \
  --selected-netlist build/r16_soc/soc_top/pre_alu.json \
  --selection build/r16_soc/soc_top/wide_alu_mapping.json --top soc_top
```

综合入口在完整路径超过 10 级时返回非零状态，同时保存全部已完成的综合与测量报告。
