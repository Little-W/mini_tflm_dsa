# FPGA 面积、时序与存储实现交接

## 目标与测量记录

SoC 顶层为 `soc_top`，板级测量顶层为 `fpga_top`，目标器件为 Artix-7 `xc7a200tfbg484-3`。生产设计的目标为：Vivado 报告的 **Slice LUTs 不超过 50,000**，完整连接图中寄存器间最长组合路径不超过 **10 个组合单元**，目标时钟为 **150 MHz**，周期约束为 **6.667 ns**。

每次完整 SoC 测量保存固定源码、综合参数、逻辑 LUT、存储 LUT、FF、DSP、BRAM 和时序状态。详细入口见 [器件测量说明](fpga_150mhz_measurement.md)。`source_manifest.json` 保存完整输入指纹，`measurement.json` 汇总实际 Vivado 资源和时序报告。独立保存本地 LUT 原语计数及物理位置计数。

10 级限制用于检查全部同步数据与控制端点之间的组合路径；150 MHz 通过状态使用布线后的建立时间和保持时间报告。综合结果分别保存资源条件、完整连接图的深度条件与频率确认状态。

## FPGA 生产配置与完整功能

参数来自 [config/npu_fpga.mk](../config/npu_fpga.mk)。完整 SoC 保留以下配置与功能。

| 项目 | 配置 |
| --- | --- |
| 计算阵列 | 16 × 16，共 256 个计算 PE |
| 向量计算 | 8 个 PE，保留深度卷积、池化、Add、Softmax 等操作 |
| 数据精度 | INT8、INT16 输入，INT32 累加与部分和 |
| 数据流与量化 | WS、IS，逐张量和逐通道量化 |
| NPU AXI 数据宽度 | 64 位，读写在途事务各 4 个 |
| im2col 缓存 | 4,096 字节 |
| IA/PS 共享数据 RAM | 7 个银行，每个 8,192 字节，共 57,344 字节 |
| IA 缓存与部分和帧数 | `IA_CACHE_BLOCKS=4`，`PS_FRAME_COUNT=16` |
| PS 最大存储池 | 49,152 字节，直接保存 INT32 |
| 量化计算通道 | 2 个，每行 16 个元素分 8 批计算 |
| 量化整组缓冲 | 512 行，每行 513 位 |
| NPU 数组容量预算 | 131,072 字节，范围为 `buffer-ram` |
| CPU 与存储器 | 完整 PicoRV32，乘除法启用；65,536 个 32 位字，共 256 KiB |
| CPU RAM 物理端口与指令缓存 | 64 位物理端口；指令缓存关闭 |

FPGA 编译定义为 `SYNTHESIS=1`、`XILINX_FPGA=1`、`XILINX_CLK_WIZ_IP=1`、`GEMPACT_PS_COMPRESS=1`、`GEMMORA_PS_POOL_BYTES=49152` 和 `GEMMORA_PS_FORCE_RAW=1`。`GEMPACT_PS_COMPRESS` 用于启用共享存储和帧调度，生产部分和采用 INT32 存储。

容量检查使用实际数组声明和生产层次展开，核对数据、标签、参数与状态存储；CPU RAM 单独计入 SoC 资源。逻辑容量、ASIC 宏取整后的物理容量以及 FPGA 资源分别报告。功能、容量、并行规模和公开接口周期均属于后续优化必须保持的设计条件。

## RTL 组织与实现方式

组合选择、比较、移位、算术和存储采用普通可综合 RTL 及命名生成块，LUT、BRAM、DSP 和触发器由工具推断。FPGA 时钟门控使用 `BUFGCE`。修改继续遵循 `rtl-design` 和 `synthesizable-rtl-style`，使用明确的位宽、符号、事件优先级和实例连接，说明性注释使用中文。

公共存储模块统一命名为 `regfile`，文件为 `rtl/common/regfile.v`。端口、读写周期、写入分组和 `p_ram_style` 属性由实例参数表达。同步读取分支保留读使能暂停时的输出，同址读写返回写入前的数据；数据有效性由对应控制状态管理。

IA 标签和 PS 重放使用同步存储结构。IA 写入预选在已有写命令寄存阶段准备共享银行的 128 位数据，原有写端口的地址、掩码、有效位和接受周期保持。生产 DMA 布局关系通过真实 DMA 输出的归纳证明后，用于启用专用参数；通用模块的默认参数保留完整输入行为。对应检查见 [DMA 输出布局](../test/dma_source_layout/README.md) 和 [共享存储写数据预选](../test/ia_shared_write_stage/README.md)。

量化缓冲在最终输出组开始前预留整组容量，覆盖尚在阵列中、存储中、同步读出中和算术流水中的全部未完成行。每输出一行释放一行预留，下一最终输出组等待当前组完成。参数在未完成组期间保持稳定；队列与参数持续就绪时，两个量化通道每 8 个周期输出一行。完整的 INT8、INT16 舍入、限幅和 tile 完成标志随数据保持，详见 [分时量化与整组缓冲](../test/requant_time_share/README.md)。

## ASIC 量化缓冲与 DC 流程

### 默认配置和生产配置

ASIC Makefile 默认读取 [config/npu.mk](../config/npu.mk)，通过 `NPU_CONFIG` 可以选择其他配置。

| 项目 | ASIC 默认配置 | FPGA 生产配置用于 ASIC 展开 |
| --- | --- | --- |
| 配置文件 | `config/npu.mk` | `config/npu_fpga.mk` |
| 计算阵列与 AXI 数据宽度 | 16 × 16，64 位 | 16 × 16，64 位 |
| 共享银行 | 9 × 2,048 字节 | 7 × 8,192 字节 |
| `IA_CACHE_BLOCKS` | 2 | 4 |
| `PS_FRAME_COUNT` | 4 | 16 |
| 量化计算 | 完整并行 | 两个物理计算通道 |
| 分时量化整组缓冲 | 该路径不启用 | 513 位 × 512 行 |
| ASIC 默认目标频率 | 50 MHz | 由 `TARGET_FREQ_MHZ` 指定，默认仍为 50 MHz |

DC 的 `3_read_design.tcl` 定义 `SYNTHESIS`、`ASIC_SYNTHESIS` 和 `ASIC_SRAM`，读取 `prepare_dc_sources.py` 生成的源文件列表，并加入 `asic/rtl/smic40_sram_1r1w.sv`。共享存储与 RAW32 部分和的编译定义由所选 Make 配置提供。

标准单元时序库由 `STD_ROOT` 指定，SRAM 库由 `SRAM_ROOT` 指定；标准单元作为目标库，`RAMTP128X16` 与 `RAMTP1024X16` 的 `.db` 文件作为链接库。展开并链接后，`check_requant_storage.tcl` 生成 `npu_top_requant_storage.rpt`，检查实际量化缓冲的宏实例、容量和 `regfile` 子实例。分模块综合使用相同的公共 RTL、宏封装、参数与展开结果。详细运行说明见 [ASIC 综合环境](../asic/README.md) 和 [ASIC 综合与路径优化](asic_synthesis.md)。

### 513 位、512 行的 SRAM 结构

`requant_group_buffer` 在 `ASIC_SRAM` 下通过 `smic40_sram_1r1w` 保存每行全部 16 个 INT32 数据和一个 `tile_done` 标志。

| 项目 | 数值 |
| --- | ---: |
| 逻辑存储容量 | 513 × 512 = 262,656 位，32,832 字节 |
| 宏型号与尺寸 | `RAMTP128X16`，128 行 × 16 位 |
| 深度方向分组 | 4 |
| 每个深度分组的宽度切片 | 33 |
| SRAM 宏总数 | **132** |
| 物理宏容量 | 270,336 位，33,792 字节，即 33 KiB |
| 填充容量 | 7,680 位，960 字节 |
| 该缓冲的推断数据存储与 `regfile` 子实例 | 均为 0 |
| 控制和读取 bank 选择寄存器 | 41 位 |

每行最后一个宽度切片仅使用一位，其余 15 位写数据为零且写掩码关闭。读使能有效时，同步更新整行数据及读取 bank；读使能暂停时，宏输出和读取 bank 都保持。复位和清空重置队列控制，不要求复位 SRAM 数据阵列。

真实宏的同址并发读写行为不用于实现队列功能。控制归纳证明从合法整组预留、输入不超过预留数量、输出仅消费已发射行等协议条件导出读写地址互斥。功能模型保存全部宏数据和写掩码，并在同址并发读写时报告冲突。

### 已保存的检查结果

| 检查 | 范围与结果 |
| --- | --- |
| [ASIC/FPGA 结构检查](../test/requant_group_buffer_asic/README.md) | 13 组参数分别展开两个分支，**26 项通过**；检查完整数据位、掩码、时钟、使能、读取 bank 和宏数量 |
| [SRAM 功能比较](../test/requant_group_buffer_memory/README.md) | **10 种深度通过**；比较实际封装、同步 SRAM 功能模型、通用存储分支与独立队列，覆盖满容量、回绕、边界、背压、复位和输出保持 |
| [控制归纳证明](../test/requant_group_buffer_memory/measurement.json) | **10 种深度通过**；证明预留守恒、地址范围和合法并发读写地址不同 |
| [完整 NPU 的 ASIC 结构检查](../test/requant_group_buffer_npu/README.md) | 使用真实 DC 源文件准备流程，在实际 `u_vec_requant` 层次确认 132 个宏和完整 513 位行；保留 **256 个计算 PE、8 个向量 PE** |
| DC 流程与分模块源文件检查 | `test/asic_requant_storage/` 的 8 项测试通过，检查存储报告条件和公共源文件收集 |

结构检查覆盖 `p_lanes=1/3/16`，行数覆盖 `1/15/16/17/127/128/129/511/512/513/1024/2048/2049`，包含非二次幂深度。功能与归纳检查的深度为 `1/3/16/127/128/129/511/512/513/1024`。

完整 NPU 结构检查使用 Yosys 0.71 的 Slang 前端和 SRAM 端口黑盒，执行真实层次展开、连接与存储检查。Design Compiler 工艺映射、宏时序模型仿真及 ASIC 静态时序尚未在该检查中执行；这些结果由实际工艺工具和库文件生成。

## FPGA 验证与测量方法

完整 NPU 功能检查使用生产 FPGA 分支和相同版本的原语功能模型，覆盖完整运算、共享银行及 PS 容量、恢复、输出模式和紧凑输入格式。每次执行分别保存源码摘要、构建记录、任务结果与容量结果。模块级形式比较包含相关公开输出、无效周期和同周期事件优先级。

本地 Yosys 与 ABC9 完成展开、算术和存储综合及 LUT 映射。直接 RTL 的比较不启用额外 DSP 替换。可选宽算术 DSP 实验分别记录其选择参数、预算与组合依赖；`ONE48` 和 `FOUR12` 输出位依赖分析见 [96 项符号检查](../test/fpga_dsp_alu4/dependencies.json)。可选实验与证明命令见 [开源 FPGA 综合与资源分析](open_fpga_synthesis.md)。

组合路径按实际寄存器来源、同步数据和控制输入及 DSP 内部寄存边界计算。所有组合单元需完成分类，连接图需通过组合环检查。面积成本用于指导映射，完整物理占用由打包、合法配对和布局决定。配对阶段保留功能单元和真值表，并在布局后核对全部单元的位置及逻辑引脚对应关系。

## 运行命令

以下命令从仓库根目录执行。Python 环境需可导入项目使用的 `pyosys` 并支持 `read_slang`，Verilator 使用支持当前 SystemVerilog 的版本。

```sh
python3 test/npu_registered_fault/run.py \
  --out build/production_npu --verilator verilator-modern \
  --jobs 1
python3 -m unittest discover -s test/capacity -p 'test_*.py'
python3 test/ps_channels/run_npu_structure.py \
  --out build/production_structure --verilator verilator-modern

python3 test/requant_group_buffer_asic/check_structure.py \
  --out build/requant_group_buffer_asic
python3 test/requant_group_buffer_memory/run.py \
  --out build/requant_group_buffer_memory --verilator verilator-modern --jobs 1
python3 test/requant_group_buffer_memory/run_control.py \
  --out build/requant_group_buffer_control
python3 test/requant_group_buffer_npu/run.py \
  --source-root "$PWD" --out build/requant_group_buffer_npu
python3 -m unittest discover -s test/asic_requant_storage -p 'test_*.py'
```

完整板级测量与直接 RTL 的本地结构比较分别使用独立输出目录。

```sh
vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_fpga_150
VIVADO_RUN_IMPL=1 vivado -mode batch -source scripts/fpga/vivado_synth_fpga.tcl \
  -tclargs build/vivado_fpga_150_impl

python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --out build/soc_pre --through pre_lut \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock
python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_pre/soc_top --out build/soc_cost/soc_top \
  --mode physical-cost --small-lut-area-cost 1 \
  --max-lut-inputs 6 --wire-delay-ps 500 --delay-target-ps 6667 \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock
python3 test/soc_rtl_optimization/run_physical.py \
  --source build/soc_cost/soc_top --out build/soc_physical \
  --nextpnr /path/to/nextpnr-xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv
```

ASIC 默认综合与同容量生产参数展开分别使用以下入口。`STD_ROOT`、`SRAM_ROOT` 和 Synopsys 工具需由实际环境提供。

```sh
make -C asic/synthesis syn \
  STD_ROOT="$STD_ROOT" SRAM_ROOT="$SRAM_ROOT"
make -C asic/synthesis elaborate \
  NPU_CONFIG="$PWD/config/npu_fpga.mk" \
  STD_ROOT="$STD_ROOT" SRAM_ROOT="$SRAM_ROOT"
```

每次测量保存固定源码、工具与库的 SHA-256、完整参数、命令、原始报告和结果摘要。恢复测量时先核对这些内容，再继续相应阶段。后续执行顺序见 [测量与优化说明](fpga_next_optimization.md)。
