# 完整 SoC 与 ASIC NPU 实现说明

## 目标与配置

FPGA 综合顶层为 `soc_top`，板级顶层为 `fpga_top`，器件为 Artix-7 `xc7a200tfbg484-3`。布局前 LUT 目标为 **50,000**，最长寄存器间组合路径目标为 **10 个组合单元**，重点路径按少于 7 级优化。时钟目标为 **150 MHz**，周期约束为 **6.666667 ns**。ASIC 生产顶层为 `npu_top`，总单元面积目标为 **3,500,000**。

当前源码、资源、路径和功能检查见 [完整 SoC 检查](fpga_150mhz_optimization.md)。模块与文件的组织见 [模块说明](rtl_module_layout.md)，工艺参数见 [ASIC 生产配置](asic_npu_r16_150.md)。

| 项目 | FPGA SoC | ASIC NPU |
| --- | --- | --- |
| 计算阵列 | 16 × 16 | 16 × 16 |
| 向量 PE | 8 | 16 |
| 总线数据宽度 | 64 位 | 64 位 |
| 内部地址宽度 | 32 位 | 19 位 |
| 共享存储 | 7 × 8,192 字节 | 7 × 8,192 字节 |
| im2col 缓存 | 4,096 字节，128 字节缓存行 | 4,096 字节，128 字节缓存行 |
| PS 帧数与 RAW 空间 | 16 帧，49,152 字节 | 16 帧，49,152 字节 |
| 量化计算通道 | 2 | 2 |
| 量化输入缓冲 | 513 位 × 256 行 | 513 位 × 256 行 |
| CPU 与 CPU RAM | PicoRV32，256 KiB RAM | NPU 综合范围之外 |

生产设计保留 WS、IS、INT8、INT16、逐张量与逐通道量化，以及 im2col、深度卷积、池化、Add 和 Softmax。容量检查分别统计逻辑数据、参数和状态容量，ASIC 宏的物理容量及 FPGA 资源。

## RTL 与量化组织

每个模块或 package 使用独立源文件。NPU 文件长度以少于 1,500 行为维护目标，同一字段的流水状态使用阶段数组。算术、比较、选择、移位及 FPGA 存储由普通 RTL 描述，资源由综合工具推断。说明性注释使用中文。

`vec_requant` 管理配置、参数访问、WS/IS 顺序、输入组和输出组装，`requant_compute_lane` 实现 INT8/INT16 的单通道量化。逐张量参数广播到通道入口，逐通道参数按元素读取。七级算术流水线由通用乘法、移位、舍入和裁剪组成。FPGA 的两个计算通道每八个发射周期处理一行，256 行输入缓冲保存阵列结果。

向量深度卷积在 `SHARED_QUANT_ENABLE` 配置下通过量化请求接口共享 `vec_requant`；本地向量配置通过共用标量乘法与舍入单元完成相应运算。Add、平均池化和 Softmax 复用本地标量算术。各配置的数值与周期行为独立检查，具体接口见 [量化说明](unified_requant.md)。

## 同步存储

公共 `regfile` 使用同步读取、按组写入掩码和读使能保持。需要 SRAM 的 ASIC 配置经 `smic40_sram_1r1w` 映射至工艺库宏。状态与有效标志决定数据可用性，数据阵列采用适合目标存储的读写模板。

生产配置的 `IA_COMPACT_ENABLE=0`，量化输入缓冲为 513 × 256 = **131,328 位**。ASIC 使用 **33 个 `RAMTP1024X16`**，物理容量为 **540,672 位**。每行最后一个宽度切片仅使用一位，其他位的写掩码关闭。同步读取暂停时保存宏输出及读取选择状态。

完整 ASIC 生产结构包含 **60 个 `RAMTP128X16`** 和 **105 个 `RAMTP1024X16`**，合计 **165 个 SRAM 宏**。结构检查保留 256 个阵列计算单元与 16 个向量 PE。实际单元面积和时序由 DC 读取标准单元库及 SRAM 库后生成。

## 功能与结构检查

完整 FPGA 与 ASIC 功能检查覆盖矩阵运算、容量边界、输出模式及紧凑输入格式，并检查帧地址、FIFO、DMA、复位和错误恢复。模块级验证覆盖完整算术输入、暂停、清空、同周期事件和必要的四态行为。

ASIC 功能仿真使用同步读、逐位写掩码和同址并发检查模型。DC 输入准备使用真实生产参数、源文件清单及约束副本；结构检查核对宏连接与计算规模。工艺映射状态与功能仿真状态分别记录。

## 运行命令

```bash
python3 test/rtl_layout/check.py --out build/rtl_layout
python3 test/fpga_integration/run.py --out build/fpga_integration --verilator verilator --jobs 1
python3 test/asic_integration/run.py --out build/asic_integration --verilator verilator --jobs 1
python3 test/requant_group_buffer_npu/run.py --source-root . --out build/asic_structure
python3 scripts/fpga/open_fpga_synth.py --source-root . --cases soc_top \
  --out build/soc_measurement --max-register-path-cells 10 --require-register-path-limit
python3 scripts/asic/run_ps_synthesis.py --profile npu_r16_150 \
  --prepare-only --out build/asic/npu_r16_150_prepare
```

板级布局布线入口如下：

```bash
VIVADO_RUN_IMPL=1 vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_fpga_150_impl
```

DC 生产入口默认请求 5,000 个不同建立时间端点和 5,000 个不同保持时间端点，同时导出完整路径、分层面积、设计检查及 SRAM 时钟弧检查。完整运行参数见 [ASIC 综合配置](asic_npu_r16_150.md)。
