# 共享 IA/PS RAM 的物理映射

共享数据 RAM 在 [`ia_ps_shared_ram.sv`](../rtl/npu/buffers/ia_ps_shared_ram.sv)
中提供两种实现。固定通道配置使用 `ia_ps_channel_ram`，轮转配置使用
`ia_ps_shared_ram`。数据字宽为 128 位，容量按 bank 分配；固定通道实现进一步
将可共享的 bank 划分为独立存储段，为四个 PS 通道提供并行访问。

矩阵软件在任务开始前为 IA 分配 1 或 2 个 bank；总数达到 8 个时也可分配 4 个，
其余容量用于 PS。任务执行期间分配保持固定。VCE 的分配由顶层在接收任务时自动设置。

## 端口译码与访问时序

共享 RAM 接收两个 IA 端口和四个 PS 端口。未配置状态下的访问、越界访问以及
同地址读写冲突均记录容量错误；冲突写入被禁止，重新配置能够清除错误状态。

| 实现 | IA 地址单位 | PS 端口地址单位 | PS 端口含义 |
| --- | --- | --- | --- |
| 固定通道 `ia_ps_channel_ram` | 128 位字 | 512 位部分和行 | 端口编号选择行内的 128 位数据段 |
| 轮转 `ia_ps_shared_ram` | 128 位字 | 128 位字 | 地址高位选择 PS bank，低位选择 bank 内行号 |

IA 地址按分配数量使用固定比特选取 bank 和行。轮转实现的各物理 bank 使用
独立的读写授权逻辑；同类访问冲突时，按 IA 端口 0、IA 端口 1、PS 端口 0 至 3
的顺序选择第一个请求，并记录错误。固定通道实现使用独立 PS 存储段处理四口访问。
两种实现都在时钟边沿接收读地址，同时保存返回数据的选择信息，数据在该边沿后有效。

`ia_loader_cache_mgr` 将 IA 写命令的地址、数据、字节掩码和使能一起寄存，下一时钟边沿写入物理 RAM。此级寄存每周期能够接收一条写命令。已有的分组启动和读取地址阶段保证最后一条填充命令先于对应行读取完成写入，连续行输出的周期保持不变。

## 向量任务访问

`npu_top` 在矩阵任务与向量任务之间切换共享 RAM 的访问权。VCE 使用
[`vector_shared_store`](../rtl/npu/buffers/vector_shared_store.sv) 访问已有物理 RAM，
权重存入 IA 分区，量化前的 INT32 结果存入 PS 分区。两类任务互斥执行；
配置周期不接受数据访问，任务完成前等待同步读取返回。

VCE 的权重读写宽度为 128 位，PS 读写宽度为 512 位。权重使用 IA 端口 0，
PS 使用四个并行 128 位端口。固定通道实现中，PS 地址为共同的 512 位行号；
轮转实现中，逻辑行号分别映射到四个独立 PS bank 的相同行。
读取数据由物理 RAM 输出寄存器保持，适配模块只保存配置、错误和读取有效状态。

顶层按 `DW_MAX_TAPS × SIZE` 自动选择能够容纳权重的 1、2 或 4 个 IA bank，
同时为 PS 保留至少四个 bank。默认 49 个位置、16 个通道需要 784 B，
一个 2 KiB IA bank 可以容纳；默认结果暂存使用一行 64 B 的 PS 空间。
PE 的当前累加值保留在工作寄存器中，以支持连续乘加。
完整的访问时序和寄存器职责见[向量计算引擎](vector_engine.md)。

## 目标配置与数据容量

| 目标 | 配置文件 | 默认 bank 大小 | 默认 bank 数量 | 默认共享数据容量 | 支持的 bank 大小 |
|---|---|---:|---:|---:|---|
| 通用及 ASIC | [`config/npu.mk`](../config/npu.mk) | 2 KiB | 9 | 18 KiB | 2、4、8 KiB |
| Xilinx 7 series FPGA | [`config/npu_fpga.mk`](../config/npu_fpga.mk) | 8 KiB | 7 | 56 KiB | 8 KiB |

两种目标均支持 6 至 9 个 bank。配置字段 `SHARED_BANK_BYTES` 使用字节，公开取值为 2048、4096、8192；FPGA 工程入口进一步要求 8192。`NPU_CONFIG` 可选择配置文件，FPGA 入口同时检查显式文件和环境变量覆盖后的参数。

共享数据字节数为 `SHARED_BANK_BYTES × SHARED_BANK_COUNT`，每个 bank 的行数为 `SHARED_BANK_BYTES / 16`。此容量包括 IA 和 PS 数据。PS 目录、标签、控制寄存器、输出缓冲以及 SoC 主存分别统计。外部 AXI4 可选 32 或 64 位，内部 bank 接口均为 128 位；AXI-Lite 控制接口使用固定 32 位数据和 16 位地址。

## ASIC SRAM 宏

ASIC 路径使用 [`smic40_sram_1r1w`](../asic/rtl/smic40_sram_1r1w.sv)，共享 bank 的 `MACRO_DEPTH=128`。一个 `RAMTP128X16` 提供 128 行、每行 16 位，共 256 字节。八个宏并排形成 128 位数据宽度；深度扩展采用完整的 128 行组。

| 单 bank 数据容量 | 128 位行数 | 深度组数 | 每 bank 宏数量 | 七 bank 宏数量 | 七 bank 物理数据容量 |
|---:|---:|---:|---:|---:|---:|
| 2 KiB | 128 | 1 | 8 | 56 | 14 KiB |
| 4 KiB | 256 | 2 | 16 | 112 | 28 KiB |
| 8 KiB | 512 | 4 | 32 | 224 | 56 KiB |

任意合法 bank 数量下，宏数量为 `SHARED_BANK_COUNT × 8 × (SHARED_BANK_BYTES / 2048)`。物理数据位与逻辑数据位相等，没有因深度或字宽取整而空置的数据容量。

[`check_asic_mapping.py`](../test/shared_ia_ps/check_asic_mapping.py) 通过生产共享 RAM 和 SRAM 封装展开实际宏实例，覆盖 3 种 bank 大小与 4 种 bank 数量，共 12 个配置。检查包括宏数量、端口位宽、读写时钟和控制连接。宏使用接口黑盒声明；实际工艺时序、面积和功耗由 [ASIC 综合流程](../asic/README.md) 及工艺库计算。

```bash
python3 test/shared_ia_ps/check_asic_mapping.py \
  --yosys /path/to/yosys --out build/shared_ram_mapping/asic
```

结果写入 `summary.json`，每个配置保存展开命令、网表摘要、逻辑数据位、物理数据位和未使用数据位。

## FPGA block RAM

FPGA 路径保留 `ram_style="block"`。每个 8 KiB bank 为 128 位 × 512 行，映射为两个 `RAMB36E1`。每个 primitive 采用 SDP 模式，提供 512 行 × 64 位数据，另有 512 行 × 8 位 parity。该组织及独立同步读写能力见 [AMD UG953：RAMB36E1](https://docs.amd.com/r/2025.2-English/ug953-vivado-7series-libraries/RAMB36E1)。

| Bank 数量 | `RAMB36E1` 数量 | 完整数据容量 | 独立 parity 容量 | 数据与 parity 总容量 | 未使用的数据容量 |
|---:|---:|---:|---:|---:|---:|
| 6 | 12 | 48 KiB | 6 KiB | 54 KiB | 0 |
| 7 | 14 | 56 KiB | 7 KiB | 63 KiB | 0 |
| 8 | 16 | 64 KiB | 8 KiB | 72 KiB | 0 |
| 9 | 18 | 72 KiB | 9 KiB | 81 KiB | 0 |

每个数据地址和数据位均可寻址，数据容量利用率为 100%。parity 写入端保持为零，parity 容量不属于软件可见的 IA/PS 存储。按数据与 parity 的总位数计算，数据占比为 8/9。

[`check_shared_ram.py`](../fpga/vivado/tflm_ai_dsa_soc/scripts/check_shared_ram.py) 使用 Yosys `read_slang` 和 `synth_xilinx -family xc7`，对上述四种配置进行实际映射。它先核对每个 bank 的 128 位宽、512 行、同步 1R1W 结构，再检查每 bank 两个 `RAMB36E1`、SDP 模式、parity 输入和完整数据容量。映射结果中的 `RAMB18E1` 与 LUTRAM 数量均为零。

```bash
python3 fpga/vivado/tflm_ai_dsa_soc/scripts/check_shared_ram.py \
  --yosys /path/to/yosys --out build/shared_ram_mapping/fpga
```

`summary.json` 记录 Yosys 版本、源码摘要、各类 RAM、逻辑 LUT 和外部触发器数量，并区分物理数据位与 parity 位。这里的映射结果来自 Yosys。Vivado 的综合、布局布线和时序报告由 [FPGA 工程流程](../fpga/vivado/tflm_ai_dsa_soc/README.md) 生成。

FPGA Tcl 测试覆盖默认配置、显式覆盖、AXI32/64、工程导出与重新打开，并在创建工程前检查 bank 大小：

```bash
python3 fpga/vivado/tflm_ai_dsa_soc/scripts/test_npu_config.py \
  --out build/shared_ram_mapping/fpga_configuration \
  --picorv32 /path/to/picorv32
```

## 软件分配和容量报告

IA 的双缓冲容量为紧凑 S8 的 `512R` 字节或 S16 的 `1024R` 字节。PS 按实际 bank 数和每 bank 深度保留空间，并受 1024 行目录限制。RAW32 的中间行上限为四个 128 位字；严格 S24、S16 上限分别为三个、两个字。Sparse128 和差分编码可降低实际占用，任务分配仍根据已证明的长度上限计算。详细规则见 [容量说明](capacity.md) 和 [硬件架构](architecture.md)。

S8 输出 FIFO 的容量随最大 IA 行组确定。默认 16 个 PS frame 下，2、4 KiB 共享 bank 对应 8 KiB S8 输出 FIFO，8 KiB 共享 bank 对应 16 KiB S8 输出 FIFO。完整容量报告分别列出 `ia_ps_shared_ram` 和 `oa_s8_fifo`，并核对 `MATRIX_OUTPUT_BANKS` 与实际 RTL 的输出 bank 数量。

[`scripts/capacity/model.py`](../scripts/capacity/model.py) 的 `physical_shared_memory` 报告包括：

| 字段 | 含义 |
|---|---|
| `logical_data_bytes` | IA/PS 共享逻辑数据容量 |
| `asic.macro_count` | `RAMTP128X16` 实例数量 |
| `asic.allocated_data_bytes` | ASIC 宏提供的数据容量 |
| `asic.unused_data_bytes` | ASIC 宏中未使用的数据容量 |
| `fpga.primitive_count` | `RAMB36E1` 实例数量 |
| `fpga.allocated_data_bytes` | FPGA block RAM 的数据容量 |
| `fpga.unused_data_bytes` | 未使用的数据容量 |
| `fpga.parity_bytes` | 独立 parity 容量 |
| `fpga.compatible` | 配置是否满足 FPGA 的 8 KiB bank 要求 |

完整 NPU 的逻辑数组和顺序状态由 [`check_elaboration.py`](../test/capacity/check_elaboration.py) 核对。它支持 `--config` 和 `NPU_CONFIG`，报告共享 RAM 与目录的实际展开尺寸。物理共享 RAM 检查和完整逻辑容量检查使用各自明确的统计范围。

```bash
make capacity-show NPU_CONFIG=config/npu.mk
make capacity-show NPU_CONFIG=config/npu_fpga.mk

python3 test/capacity/check_elaboration.py \
  --config config/npu_fpga.mk --verilator /path/to/verilator \
  --output-root build/shared_ram_mapping/npu_elaboration
```
