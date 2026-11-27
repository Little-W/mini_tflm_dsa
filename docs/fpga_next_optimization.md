# FPGA 测量与优化流程

## 目标与结果入口

完整 `soc_top` 使用 [生产配置](../config/npu_fpga.mk)，目标器件为 `xc7a200tfbg484-3`。LUT 目标为 **55,000**，最长寄存器间组合路径目标为 **10 个组合单元**，重点路径按少于 7 级优化。目标频率为 **150 MHz**，周期约束为 **6.666667 ns**。

当前测量与功能结果集中在 [完整 SoC 检查](fpga_150mhz_optimization.md)。布局前 LUT、布局后 Slice LUT、连接图组合深度、布线后建立和保持裕量分别记录。每项测量保存实际输入源码及 SHA-256。

## 执行步骤

1. 保存被测源码和完整硬件参数。不同模块的并行工作使用明确的文件范围，公共接口修改统一集成。
2. 从真实路径的起点寄存器、组合单元和终点寄存器确定优化表达式，检查数据、使能、选择和同步存储控制输入。
3. 使用可综合 RTL 描述算术与存储，明确位宽、符号、事件优先级及各阶段有效条件。重复阶段字段使用数组，每个模块独立保存。
4. 对候选完成算术等价、状态转移、接口等待和必要的四态检查。使用完整模块测量确认局部面积及路径变化。
5. 合入通过检查的候选，保存新的完整源码副本，执行 FPGA 与 ASIC 配置的完整 NPU 功能测试。
6. 使用相同生产参数进行完整 SoC 综合，统计 LUT、FF、DSP、RAM 及全部寄存器端点的组合深度，检查连接图完整性。
7. 使用 Vivado 运行目标器件布局布线，并检查实际资源、建立时间和保持时间。

布局布线和 ASIC 工艺映射使用各自实际工具与库。所有目标状态依据对应阶段产生的报告填写。

## 存储与容量

保留 16 × 16 阵列、8 个 FPGA 向量 PE、64 位总线、7 个 8 KiB 共享存储组、16 个 PS 帧、完整 PicoRV32 和 256 KiB CPU RAM。量化使用两个计算通道与 513 位 × 512 行输入缓冲。

ASIC 生产配置使用 16 个向量 PE。完整结构检查同时核对阵列规模、共享存储、量化缓冲、SRAM 类型和宏实例数量。软件可用容量、宏取整后的物理容量及 FPGA RAM 资源分别报告。

## 运行与结果保存

```bash
python3 test/rtl_layout/check.py --out build/rtl_layout
python3 test/fpga_integration/run.py --out build/fpga_integration --verilator verilator --jobs 1
python3 test/asic_integration/run.py --out build/asic_integration --verilator verilator --jobs 1
python3 scripts/fpga/open_fpga_synth.py --source-root . --cases soc_top \
  --out build/soc_measurement --max-register-path-cells 10 --require-register-path-limit
python3 test/requant_group_buffer_npu/run.py --source-root . --out build/asic_structure
python3 scripts/asic/run_ps_synthesis.py --profile npu_r16_150 \
  --prepare-only --out build/asic/npu_r16_150_prepare
```

完整板级入口见 [器件测量说明](fpga_150mhz_measurement.md)，工艺库参数见 [ASIC 综合配置](asic_npu_r16_150.md)。每次运行使用独立输出目录。`--resume` 检查源码、工具、参数和阶段文件摘要后复用已完成结果。较大的中间网表可无损压缩，并保存解压后的 SHA-256。
