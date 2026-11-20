# IA 写入列状态与写入范围优化

RTL 提交：`9ef45ec84e979775bbb049a58c018a83189f5dbe`。参考提交：`362870b1d17f987459768529a3ac202c8c5591ee`。

## 设计

`ia_loader.sv` 在 `ext_dma_start` 接收描述符的时钟沿保存各列的有效位。每个 DMA 通道通过固定的位区间和 `ext_dma_wr_col_base` 选择有效位，数据写入期间的列选择不再串联列偏移加法与描述符列数比较。保存范围覆盖所有可到达列，未使能通道的数据值也保持一致。窄 `REG_WIDTH` 参数继续使用原有回绕运算。

`ia_loader_cache_mgr.sv` 从已经排列到物理列的 `write_shifted_mask` 取得最高有效列，直接编码 `write_extent`。`any_lane_write` 为物理写入掩码的归约或。描述符接收、数据写入、共享 RAM 命令寄存器和读取时序保持相同周期关系。

## 功能检查

所有检查均使用上述 RTL 提交的相同文件内容。各文件 SHA256、综合网表 SHA256、形式检查和数值检查摘要保存在 [measurement.json](measurement.json)。

| 检查 | 覆盖范围 | 结果 |
|---|---|---|
| 列选择时序形式证明 | 11 组参数，`SIZE` 为 2、4、5、8、16、32、64，数据宽度为 8、16、32 位；包含窄寄存器回绕及每拍通道数超过列数的情况 | 全部通过 |
| 完整缓存模块等价证明 | 5 组参数，32、64、128 位总线，本地 RAM 与外部 RAM；13,812 个等价位 | 全部通过 |
| 官方 FPGA LUT 模型，有序预取 | 39 个公开输出逐周期比较；251 条命令，57,835 个周期，179,920 项数值检查 | 全部通过 |
| 官方 FPGA LUT 模型，32 块分组加载 | 39 个公开输出逐周期比较；81 组配置，122,287 个周期，724,032 项数值检查 | 全部通过 |
| 7 × 8192 字节共享 RAM | 4,681,255 个周期，15,022,624 项数值检查，74,900,080 项逐周期数值检查 | 全部通过 |

列选择形式证明在复位初始化后使用无界归纳，输入数据、描述符列数、写入列、通道有效位和后续复位均可任意变化。完整缓存证明同时覆盖地址、数据、写掩码和缓存状态，输入偏移保留完整 16 位取值。

共享 RAM 数值检查覆盖生产配置的 9 位紧凑偏移、每个内存分配方案的 256 个 INT8 偏移、支持宽格式的方案中全部 65,536 种 INT16 位模式、1,280 种写掩码、跨字写入及 IA/PS 同时访问。所有 12 个 C++ 编译单元启用未定义行为检查。

## 完整 IA 模块映射

使用 Yosys 的 `synth_xilinx` 和 ABC9，目标架构为 Xilinx 7 系列。两份输入的区别仅为本次修改的两个文件。参数为 `DATA_WIDTH=16`、`SIZE=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`COMPACT_S8=1`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`、`RAM_WORD_ADDR_WIDTH=12`、`PS_FRAME_COUNT=16`。

| 资源 | 参考版本 | 当前版本 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT 单元 | 5,590 | 5,693 | +103 |
| LUTRAM 对应 LUT 位置 | 176 | 176 | 0 |
| LUT 位置合计（打包前） | 5,766 | 5,869 | +103 |
| 触发器 | 3,083 | 3,101 | +18 |
| CARRY4 | 418 | 417 | −1 |
| DSP、BRAM、SRL | 0 | 0 | 0 |

| 实际连接路径 | 参考版本级数 | 当前版本级数 |
|---|---:|---:|
| 完整 IA 模块的寄存器间最大路径 | 12 | 13 |
| DMA 写入列到 RAM 写数据寄存器 | 13 | 11 |
| DMA 写入列到 RAM 写使能寄存器 | 12 | 10 |
| DMA 写入列到 RAM 写掩码寄存器 | 11 | 10 |
| DMA 通道有效位到 RAM 写数据寄存器 | 10 | 10 |
| DMA 通道有效位到 RAM 写掩码寄存器 | 8 | 9 |
| DMA 写数据到 RAM 写数据寄存器 | 9 | 9 |
| 内部寄存器到 RAM 写地址寄存器 | 6 | 4 |

路径统计沿映射后的实际逐位连接读取，包含 LUT、进位及专用选择单元。DMA 输入路径的起点使用仅供分析的输入寄存器标记，资源统计采用加入这些标记之前的网表。完整图不存在未分类单元或组合环。

本报告提供完整 IA 模块的资源和结构测量。完整 SoC 面积与跨模块路径使用整机映射结果；150 MHz 时序还需要目标器件的单元与布线延时分析。

## 复现

在仓库根目录设置工具链环境后运行：

```bash
python3 test/ia_write_admission/run_formal.py \
  --reference 362870b1 --out build/ia_write_admission/column_formal

python3 test/ia_write_layout/run_formal.py \
  --reference-ref 362870b1 --out build/ia_write_admission/cache_formal

python3 test/ia_write_admission/run_interface.py \
  --reference-rev 362870b1 --verilator verilator-modern \
  --out build/ia_write_admission/interface_fpga

python3 test/ia_shared/run.py --bank-bytes 8192 --bank-count 7 \
  --compact-offset-width 9 --jobs 1 --verilator verilator-modern \
  --out build/ia_write_admission/shared

python3 test/ia_write_admission/prepare_measurement.py \
  --reference-rev 362870b1 --out build/ia_write_admission/native_inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ia_write_admission/native_inputs/cases.json \
  --cases loader_reference loader_current --out build/ia_write_admission/native \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock

python3 test/ia_write_admission/paths.py \
  --reference build/ia_write_admission/native/loader_reference \
  --current build/ia_write_admission/native/loader_current \
  --out build/ia_write_admission/native_paths.json

python3 test/ia_write_admission/summarize.py \
  --build build/ia_write_admission --out test/ia_write_admission/measurement.json
```
