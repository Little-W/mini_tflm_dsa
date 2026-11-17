# NPU AXI-Lite Register Map

当前 NPU 配置接口已经统一为标准 AXI-Lite MMIO。寄存器从 NPU 窗口基地址 `0x1000_0000` 的 `0x000` 偏移开始连续定义，驱动侧使用字节偏移，验证侧 UVM 寄存器模型使用等价的 word offset。

## 地址表

| Byte offset | Word offset | Name | Access | Description |
|---:|---:|---|---|---|
| `0x000` | `0x000` | `NPU_REG_CTRL` | RW | 启动、数据位宽、量化模式、数据流和中断使能控制 |
| `0x004` | `0x001` | `NPU_REG_STATUS` | RO/WC | ready/busy/done/error 状态，done 使用写清除 |
| `0x008` | `0x002` | `NPU_REG_WB_DATA` | RO | 最近一次完成状态写回 |
| `0x010` | `0x004` | `NPU_REG_LHS_BASE` | RW | LHS/IA 基地址 |
| `0x014` | `0x005` | `NPU_REG_RHS_BASE` | RW | RHS/W 基地址 |
| `0x018` | `0x006` | `NPU_REG_DST_BASE` | RW | 输出基地址 |
| `0x01c` | `0x007` | `NPU_REG_BIAS_BASE` | RW | bias 基地址，可为 0 |
| `0x020` | `0x008` | `NPU_REG_K` | RW | 输出行数 / LHS rows |
| `0x024` | `0x009` | `NPU_REG_N` | RW | 内积长度 |
| `0x028` | `0x00a` | `NPU_REG_M` | RW | 输出列数 / RHS cols |
| `0x02c` | `0x00b` | `NPU_REG_LHS_STRIDE_B` | RW | LHS 行跨度，单位字节 |
| `0x030` | `0x00c` | `NPU_REG_RHS_STRIDE_B` | RW | RHS 列跨度，单位字节 |
| `0x034` | `0x00d` | `NPU_REG_DST_STRIDE_B` | RW | 输出行跨度，单位字节 |
| `0x038` | `0x00e` | `NPU_REG_LHS_ZP` | RW | LHS zero point |
| `0x03c` | `0x00f` | `NPU_REG_RHS_ZP` | RW | RHS zero point |
| `0x040` | `0x010` | `NPU_REG_DST_ZP` | RW | 输出 zero point |
| `0x044` | `0x011` | `NPU_REG_Q_MULT` | RW | per-tensor multiplier 或 per-channel multiplier 指针 |
| `0x048` | `0x012` | `NPU_REG_Q_SHIFT` | RW | per-tensor shift 或 per-channel shift 指针 |
| `0x04c` | `0x013` | `NPU_REG_ACT_MIN` | RW | 激活下限 |
| `0x050` | `0x014` | `NPU_REG_ACT_MAX` | RW | 激活上限 |
| `0x054` | `0x015` | `NPU_REG_IA_REUSE` | RW | IA cache 复用深度 |
| `0x058` | `0x016` | `NPU_REG_W_REUSE` | RW | W 侧复用窗口 |
| `0x05c` | `0x017` | `NPU_REG_DATAFLOW` | RW | `0=WS`，`1=IS` |
| `0x060` | `0x018` | `NPU_REG_ROW_GROUPS` | RW | 内部流行工作组总数，外部预计算 |
| `0x064` | `0x019` | `NPU_REG_ROW_TAIL_TILES` | RW | 最后一行工作组的 tile 数，整除时写 R |
| `0x068` | `0x01a` | `NPU_REG_COL_GROUPS` | RW | 内部流列工作组总数，外部预计算 |
| `0x06c` | `0x01b` | `NPU_REG_COL_TAIL_TILES` | RW | 最后一列工作组的 tile 数，整除时写 W |
| `0x070` | `0x01c` | `NPU_REG_CONFIG_ABI` | RO | 配置 ABI 版本，当前为 2 |
| `0x0e4` | `0x039` | `NPU_REG_MATRIX_CAPS` | RO | 矩阵布局、数据流、IA 和部分和容量 |
| `0x0e8` | `0x03a` | `NPU_REG_MATRIX_PS_ROWS` | RO | 物理部分和 RAM 行数 |
| `0x0ec` | `0x03b` | `NPU_REG_MATRIX_OUTPUT_BANKS` | RO | 低 16 位为 INT8 输出 bank 数，高 16 位为 INT16 输出 bank 数 |
| `0x0f0` | `0x03c` | `NPU_REG_DMA_MAX_BYTES` | RO | 单个 AXI DMA 突发允许的最大字节数 |
| `0x0f4` | `0x03d` | `NPU_REG_AXI_DATA_BITS` | RO | 物理 AXI 数据端口宽度，单位 bit，支持 32 或 64 |
| `0x0fc` | `0x03f` | `NPU_REG_ID` | RO | 固定为 `0x4e50_5531` |

## CTRL 位定义

| Bit | Name | Description |
|---:|---|---|
| 0 | `NPU_CTRL_START` | 写 1 产生单周期 start pulse |
| 1 | `NPU_CTRL_CFG_16BITS_IA` | LHS/IA 使用 int16 |
| 2 | `NPU_CTRL_PER_CHANNEL` | 量化参数按 channel 读取 |
| 3 | `NPU_CTRL_DATAFLOW_IS` | `1=IS`，`0=WS` |
| 4 | `NPU_CTRL_IRQ_ENABLE` | `1` 表示任务完成后允许 `irq` 拉高 |
| 5 | `NPU_CTRL_CFG_16X8` | 使用 INT16 输入、INT8 权重和 INT16 输出 |
| 6 | `NPU_CTRL_CONV` | 使用普通 Conv 模式 |
| 7 | `NPU_CTRL_CONV_BYPASS` | 输入窗口缓存旁路 |
| 8 | `NPU_CTRL_VECTOR_ENGINE` | 使用 VCE 执行 DW、池化、Add、Softmax 或基础向量运算，与 bit 6 互斥 |
| 9 | `NPU_CTRL_LHS_TILE_PACKED` | LHS 使用 16×16 分块排列 |
| 10 | `NPU_CTRL_RHS_TILE_PACKED` | RHS 使用 16×16 分块排列 |

## STATUS 位定义

| Bit | Name | Description |
|---:|---|---|
| 0 | `SA_READY` | NPU 计算阵列 ready |
| 1 | `BUSY` | NPU 正在执行 |
| 2 | `NPU_STATUS_DONE` | 本次任务完成，写 1 清除 |
| 4:3 | `NPU_STATUS_ERR_MASK` | `00=正常`，`01=配置错误`，`10=资源缺失` |
| 5 | `REG_READY` | AXI-Lite 寄存器通路 ready |

## 软件访问

`dsa_matmul_execute()` 根据 `dsa_matmul_config_t` 计算工作组参数、配置寄存器并等待任务完成。直接使用 MMIO 时，需要在启动前写入复用窗口及四个工作组字段，具体计算方法见下节；矩阵地址、尺寸、跨度和量化参数也需按任务配置。

## ABI 2：外部预计算分组参数

CPU、模型编译器或外部调度器在 START 之前计算并写入上述四个字段。配置参数从 START 到完成期间必须保持不变。`NPU_REG_ID` 保留设备系列标识；软件用 `NPU_REG_CONFIG_ABI == 2` 判断新配置接口。

设公开 GEMM 形状为 `C[M,N] = A[M,K] × B[K,N]`。本项目寄存器命名为 `REG_K=M`（输出行数）、`REG_N=K`（归约维）、`REG_M=N`（输出列数）。WS 内部流行／列对应 M／N；IS 对应 N／M。计算分组时使用内部流维度以及外部计算得到的最终 R、W，包括容量裁剪、支持尺寸取整和 IS 调整。ABI 2 的 R/W 寄存器必须写入非零最终值，R 支持二次幂及 25，启用 frame 调度时 W 可以使用任意不超过 frame 数的正整数；均需满足当前分配的物理容量。RTL 检查参数合法性。软件函数仍允许以 0 表示请求自动选择，然后返回非零最终值。

```
row_tiles = ceil(stream_rows / array_size)
col_tiles = ceil(stream_cols / array_size)
ROW_GROUPS = ceil(row_tiles / R)
ROW_TAIL_TILES = row_tiles % R; 若为 0，则写 R
COL_GROUPS = ceil(col_tiles / W)
COL_TAIL_TILES = col_tiles % W; 若为 0，则写 W
```

`drivers/gempact_tiling.h` 提供独立 C 计算函数；`veri/top_regression/host_tiling.py` 提供相同的 Python 实现。驱动已在配置寄存器时调用 C 函数，写入显式 R、W 及四个字段。固定形状可以保存这些结果并直接配置，无须每次运行除法。

RTL 只检查非零、尾组不超过生效 R/W，以及组数字段能否放入计数器；无效配置返回 `err_code=01`。乘积关系和完整维度一致性由外部保证，RTL 不重新做除法验证。

### 矩阵能力与 AXI 位宽查询

`dsa_matrix_query()` 先验证设备 ID 和 ABI，再读取上述只读能力寄存器。`MATRIX_CAPS` 的 bit 0、1、2 分别表示 LHS 分块排列、RHS 分块排列和 IS 数据流；bit 15:8 为 IA cache 块数，bit 23:16 为部分和帧数，bit 31:24 为方形阵列边长。矩阵调度同时检查部分和 RAM 行数和输出 bank 数。

AXI64 配置下每个完整数据拍为 8 B，最多 256 拍，对应 2,048 B 突发；AXI32 配置下分别为 4 B 和 1,024 B。DMA 还按照 4 KiB 边界拆分事务。地址与行跨度始终使用字节单位，描述符长度使用物理数据拍。配置寄存器仍是 32 位 AXI-Lite。

`axi_data_bits` 和 `dma_max_bytes` 分别保存数据宽度与突发字节上限。调度结果中的 `read_beats`、`write_beats` 表示实际宽度的数据拍数；`read_words`、`write_words` 以 32 位字为单位，便于按 `words × 4` 计算总线占用字节数。尾部写回的有效字节数由 `WSTRB` 决定。

软件默认位宽依次采用显式 `DSA_SCHEDULE_AXI_DATA_BITS`、配置头提供的 `NPU_CONFIG_NPU_AXI_DATA_WIDTH` 和 32 位兼容值。初始化时，`dsa_matrix_query()` 读取的有效硬件位宽覆盖软件默认值。Prepare 保存该硬件配置下选出的执行参数，Invoke 使用已保存的参数。

内存数据拍间隔由平台通过 `DSA_SCHEDULE_READ_BEAT_CYCLES` 和 `DSA_SCHEDULE_WRITE_BEAT_CYCLES` 配置。每周期能够提供一个读数据拍的同步 RAM 使用 `DSA_SCHEDULE_READ_BEAT_CYCLES=1`。首拍等待和 outstanding 请求的成熟时间由内存控制器实现；数据拍间隔参数描述连续数据传输吞吐。

独立 RTL 仿真的 32 字 `config.mem` 保留 word29 的原有取数模式；word30 的低／高 16 位分别为行／列组数，word31 的低／高 16 位分别为行／列尾组大小。旧输入应先通过 `host_tiling.py SOURCE DESTINATION` 转换。硬件寄存器为 32 位，当前仿真描述符及计数器配置最多支持 65535 组。

## Conv 扩展：原始 NHWC 输入与硬件 im2col

GEMM 的配置 ABI 仍为 2。Conv 单独读取 `CONV_CAPS`：高 16 位为版本 1，
bit 0 表示支持 s8 Conv，bit 1 表示支持精确范围的 AXI narrow read，bit 2 表示
支持 IS Conv。标准配置返回 `0x00010007`；禁用 IS 时仍可返回 WS 能力
`0x00010003`；整体不支持 Conv 的配置返回 0。
普通 profile 的 kernel 数据通路至少为 16 位，即使 `WEIGHT_WIDTH=8` 也会提升到
16 位，因此该参数本身不会关闭 IS Conv。能力位反映实际内部数据通路。
调用端必须检查设备 ID、ABI 和基础两个能力位，选择 IS 还必须检查 bit 2。

| Byte offset | Name | 字段 |
|---:|---|---|
| `0x074` | `CONV_INPUT_BASE` | 当前 batch 的原始 NHWC 输入地址 |
| `0x078` | `CONV_INPUT_HW` | 低 16 位 H，高 16 位 W |
| `0x07c` | `CONV_CHANNELS` | 低 16 位完整 Cin，高 16 位当前组 Cin |
| `0x080` | `CONV_GROUP_OFFSET` | 当前输入通道组的起点 |
| `0x084` | `CONV_KERNEL_HW` | 低 16 位 Kh，高 16 位 Kw |
| `0x088` | `CONV_OUTPUT_HW` | 低 16 位 Oh，高 16 位 Ow |
| `0x08c` | `CONV_STRIDE_HW` | 低 16 位 stride_h，高 16 位 stride_w |
| `0x090` | `CONV_DILATION_HW` | 低 16 位 dilation_h，高 16 位 dilation_w |
| `0x094` | `CONV_PADDING_HW` | 低 16 位 pad_top，高 16 位 pad_left |
| `0x098` | `CONV_INPUT_OFFSET` | 有符号输入校正值，范围 −127 至 128 |
| `0x09c` | `CONV_CAPS` | 只读能力及扩展版本 |
| `0x0a0` | `CONV_HITS` | 本次任务的缓存命中数 |
| `0x0a4` | `CONV_MISSES` | 本次任务的缓存缺失数 |
| `0x0a8` | `CONV_READ_BYTES` | 本次任务的原始输入读取字节数 |
| `0x0ac` | `CONV_CYCLES` | 本次任务周期计数 |

CTRL bit 6 为硬件 Conv，bit 7 为输入缓存旁路。Conv 的 bit 3 选择 WS / IS；
bit 1=1（逻辑激活矩阵为校正后的 s16）、bit 2=1（逐通道量化）、bit 5=0（s8 输出）。
输入 s8 仍以原格式存放于 DDR。`LHS_ZP=RHS_ZP=0`，输入 offset 只在 block DMA
内部的 Conv 前端加一次；
padding 在校正后为零。既有 GEMM 每次完整写入 CTRL，因此不会继承 Conv 模式。

项目寄存器 `K=Oh×Ow`、`N=Kh×Kw×group_c`、`M=当前组输出通道数`。
普通布局的权重直接使用 OHWI，`RHS_STRIDE_B=N`；也可使用 Prepare 生成的 packed 权重。
`DST_STRIDE_B` 为完整输出 Cout，组地址只加当前组的通道起点。
`LHS_STRIDE_B=roundup(N,SIZE)×2` 供原 IA 调度使用；硬件直接取得 tile 的
p0/q0，外部存储器中不分配或读取展开矩阵。WS 由 ia_loader 提交 im2col 请求，
IS 由 kernel_loader 提交；两者均从 block DMA 获取相同的普通矩阵块返回接口。
IS 的驻留排列和输出转置继续由原 kernel buffer / 写回路径处理。

`dsa_conv_s8_execute()` 每次处理一 batch 的一个通道组，字段逐项写 MMIO。
`dsa_conv_s8_config_t.dataflow_mode` 支持 0=WS、1=IS、2=AUTO；零初始化选择 WS。
两种数据流的公开 K/N/M、地址和张量布局相同。NMSIS 默认使用 AUTO，在准备阶段
按层评估 WS/IS、共享存储分配和复用参数。
NMSIS 公共入口在任何软件 im2col 或 scratch 检查之前分发，CPU 对 batch/group
仅循环配置命令。硬件路径的 CPU 提交不展开窗口或执行 Conv MAC。Prepare 可以
读取并打包静态权重，同时检查量化和 bias 数组及累加范围。

当前软件范围：NHWC s8、OHWI s8、s32 bias/累加、逐通道最近偶数舍入、s8 输出，
矩形卷积核、stride、dilation、padding、batch 与通道组；几何字段不超过 65535，
归约长度不超过 65535，所有张量与参数落在 32 位地址空间，量化/bias 地址按 4 字节对齐。
标准 NMSIS 的 `filter_dims.n` 不参与命令计算（TFLM 此处通常置 1）。
数值筛选保证 s32 累加、量化前正移位和输出 offset 不溢出，支持正/负 shift。

能力缺失、超出硬件支持范围或保守数值筛选未通过时，进入原 NMSIS 软件实现；
其 scratch 仍由 `_get_buffer_size_acc()` 保留。硬件路径不使用该缓冲区，允许
`ctx=NULL`。软件回退需要缓冲区的入口在缺失 ctx 时明确返回参数错误。
启动后的错误或超时返回 `NO_IMPL_ERROR`，不会在仍可能写内存的设备旁边执行软件重试。
超时不等于 DMA 被取消，平台必须先确认设备停止或复位，再重用输出内存。
输入在任务执行期间必须保持不变；当前平台驱动提供 RISC-V `fence`，不提供
特定 CPU cache 的维护操作，非一致性 cache 平台应在调用外完成必要维护。

驱动测试见 `test/conv_driver/README.md`；实际 RTL 数值验证使用 `test/conv_npu`。

## VCE 扩展

`CTRL[8]=1` 选择 `vector_engine`。图像几何复用 Conv 寄存器，
输入、权重、输出及逐通道量化参数复用公共地址寄存器。
向量和 Add 使用 `LHS_BASE`、`RHS_BASE`、`DST_BASE` 与 `NPU_REG_VECTOR_LENGTH`。

| 字节偏移 | C 标识符 | 访问 | 字段 |
|---:|---|---|---|
| `0x0b0` | `NPU_REG_VECTOR_OP` | RW | bits 3:0 操作，bit 8 表示 INT16 输入 |
| `0x0b4` | `NPU_REG_VECTOR_LENGTH` | RW | 向量元素数 |
| `0x0b8` | `NPU_REG_VECTOR_CAPS` | RO | 能力、PE 数、DW 核面积上限和版本 |
| `0x0bc` | `NPU_REG_VECTOR_CYCLES` | RO | 本次引擎周期 |
| `0x0c0` | `NPU_REG_VECTOR_COMPUTE` | RO | 运算状态周期 |
| `0x0c4` | `NPU_REG_VECTOR_DMA_WAIT` | RO | DMA 及相关等待周期 |
| `0x0c8` | `NPU_REG_POOL_MAX_TAPS` | RO | 池化窗口上限 256 |
| `0x0cc` | `NPU_REG_VECTOR_ADD_INPUT1_MULT` | RW | 输入 1 的 Q31 系数 |
| `0x0d0` | `NPU_REG_VECTOR_ADD_INPUT1_SHIFT` | RW | 输入 1 的指数 |
| `0x0d4` | `NPU_REG_VECTOR_ADD_INPUT2_MULT` | RW | 输入 2 的 Q31 系数 |
| `0x0d8` | `NPU_REG_VECTOR_ADD_INPUT2_SHIFT` | RW | 输入 2 的指数 |
| `0x0dc` | `NPU_REG_VECTOR_ADD_LEFT_SHIFT` | RW | 两输入的共同左移量 |
| `0x0e0` | `NPU_REG_SOFTMAX_MAX_DEPTH` | RO | Softmax 单行最大元素数 |

操作编码为 `0=DW_S8`、`1=AVGPOOL_S8`、`2=MAXPOOL_S8`、`3=MINPOOL_S8`、
`4=SUM`、`5=MAX`、`6=MIN`、`7=DOT`、`8=HADAMARD`、`9=ADD_S8`、`10=SOFTMAX_S8`。
Add 使用 INT8 输入输出，`OP[8]=0`。输入 offset 分别使用公共 `LHS_ZP` 和 `RHS_ZP`，
输出 offset、multiplier、shift 和激活范围同样复用公共字段。

`CAPS[3:0]` 表示 DW、池化、INT8 向量和 INT16 向量能力，`CAPS[4]` 表示设备提供池化窗口上限寄存器，
`CAPS[5]` 表示 Add，`CAPS[6]` 表示 Softmax。bits 15:8 为 PE 数，bits 23:16 为 DW 核面积上限 49，
bits 31:24 为版本 1。8 PE 返回 `0x0131087f`，4 PE 返回 `0x0131047f`。
能力不可用时返回 0。

配置在任务启动时保存，运行期间不能修改。完成、中断和 DONE 写 1 清除沿用公共接口。
描述符无效返回错误码 `01`，DMA 响应错误或装载后的量化数组无效返回 `10`。
同时选择 Conv 与 VCE 时，顶层拒绝任务。
已提交的 DMA 事务完成后才报告错误，超时后由平台确认设备停止再使用相关缓冲区。

`dsa_vector_validate()` 在提交前检查描述符，`dsa_vector_execute()` 完成能力查询、
寄存器写入和完成等待。完整描述见 [VCE 设计说明](../docs/vector_engine.md)。


## 矩阵布局和存储能力

| 字节偏移 | 名称 | 访问 | 字段 |
|---:|---|---|---|
| `0x0e4` | `NPU_REG_MATRIX_CAPS` | RO | bits 0/1 为 LHS/RHS tile-packed，bit 2 为 IS；bits 15:8 为初始 IA cache blocks，23:16 为 frame 数，31:24 为阵列边长 |
| `0x0e8` | `NPU_REG_MATRIX_PS_ROWS` | RO | 普通 PS 行数约束，0 表示不采用独立行数限制 |
| `0x0ec` | `NPU_REG_MATRIX_OUTPUT_BANKS` | RO | 低 16 位为 S8 输出 bank 数，高 16 位为 S16 输出 bank 数 |

Tile-packed 布局按输出行 tile 和归约 tile 排列，每个 tile 内保存 16 行、每行 16 个元素。尾部保持固定 tile 大小；元素宽度由任务字段决定。跨 frame 寻址使用整个矩阵的归约 tile 数。卷积激活由 im2col 生成时，不使用 LHS 的外存 tile-packed 表示。

## IA/PS 共享 bank 与部分和策略

| 字节偏移 | 名称 | 访问 | 含义 |
|---:|---|---|---|
| `0x100` | `NPU_REG_SHARED_TOTAL_BYTES` | RO | IA/PS 共享数据 RAM 总字节数 |
| `0x104` | `NPU_REG_SHARED_BANK_BYTES` | RO | 每个物理 bank 的字节数 |
| `0x108` | `NPU_REG_IA_BANKS` | RW | 分配给 IA 的 bank 数；PS 使用其余 bank |
| `0x10c` | `NPU_REG_IA_BANK_MASK` | RO | bit n 为 1 表示允许分配 n 个 IA bank |
| `0x110` | `NPU_REG_PS_DIRECTORY_ROWS` | RO | PS 目录的有效行容量 |
| `0x120` | `NPU_REG_PS_CONTROL` | RW | RAW32、frame 调度、frame 高度和严格部分和界 |
| `0x124` | `NPU_REG_PS_CAPS` | RO | PS 存储、调度、紧凑 IA 和严格部分和界能力 |
| `0x128` | `NPU_REG_PS_COMMANDS` | RO | 本次任务提交的 frame 命令数 |
| `0x12c` | `NPU_REG_PS_PRESSURE` | RO | 本次任务遇到的容量不足事件数 |
| `0x130` | `NPU_REG_PS_EARLY_FINISH` | RO | 本次任务因容量调度而优先完成的 frame 数 |
| `0x134` | `NPU_REG_PS_POOL_BYTES` | RO | 当前分配下的 PS 数据字节数 |
| `0x138` | `NPU_REG_IA_CACHE_BYTES` | RO | 当前分配下的 IA 数据字节数 |

`PS_CAPS` 的 bits 31:24 为版本 1，bits 23:16 为 frame 数，低位定义如下：

| bit | 能力 |
|---:|---|
| 0 | 可寻址 PS frame 存储 |
| 1 | 独立 K 进度及容量调度 |
| 2 | IA 紧凑 S8 存储 |
| 3 | 本构建强制 RAW32 |
| 4 | IA/PS 共享 bank RAM |
| 5 | 接受软件证明的 S16/S24 部分和长度上限 |

`PS_CONTROL` 的字段如下：

| 位 | 含义 |
|---|---|
| 0 | 1 强制 RAW32；0 允许自适应行编码。本构建强制 RAW32 时始终使用原始存储 |
| 1 | 1 请求逐 frame 调度；0 由窗口形状和容量决定采用连续调度或逐 frame 调度 |
| 3:2 | frame 行高：0 由硬件选择，1 为一个 tile，2 为两个 tile，3 为整个 R 组 |
| 5:4 | 0 使用硬件通用范围检查；1 为严格 S16 上限，每行至多 2 个 128 位字；2 为严格 S24 上限，每行至多 3 个字；3 为非法配置 |
| 31:6 | 保留，写入零 |

frame 行高以有效矩阵行为单位，最后一个 frame 按剩余行数截短。编码策略与调度方式分别配置，连续调度也支持压缩。自适应编码可选择重复行、Sparse128、差分 Rice、S16、S24 或 RAW32。强制 RAW32 时，每个中间行使用 4 个 128 位字，容量计算同样使用四个字的上限。

软件在 `PS_CAPS[5]=1` 时可提交严格部分和界。Prepare 调用 [`dsa_ps_bound_s8`](dsa_ps_bound.h)，读取固定权重并计算所有合法输入下需要保存的 K16 前缀范围。该计算不读取运行时激活，bias 在最终 K 后加入。S16/S24 字段指中间部分和值的取值范围。任务执行期间权重和相关 offset 保持不变。`ps_frame_store` 核对每个编码记录的实际字数，超出声明上限会报告容量错误。`PS_CONTROL[5:4]=0` 时，RTL 根据输入格式、offset 和归约长度选择通用 S24 上限或 RAW32 上限。

共享分配在 START 前写入。默认七 bank 构建的 `IA_BANK_MASK=0x16`，支持 IA=1、2、4；非法 bank 数的写入返回 AXI-Lite `SLVERR`，保持原配置。运行期间配置写入被拒绝，STATUS 的 DONE 写清除仍可用。共享能力关闭时，`SHARED_TOTAL_BYTES`、`SHARED_BANK_BYTES`、`IA_BANK_MASK` 和 `PS_DIRECTORY_ROWS` 返回零。

`SHARED_BANK_BYTES` 支持 2048、4096、8192，`SHARED_BANK_COUNT` 支持 6 至 9。通用及 ASIC 配置默认 2048 B × 7；FPGA 工程使用 8192 B bank，默认七个 bank。驱动用总字节数除以单个 bank 字节数得到物理 bank 数。每个 PS bank 可保存 `SHARED_BANK_BYTES / 16` 个 128 位字，目录容量通过 `PS_DIRECTORY_ROWS` 单独查询。寄存器报告完整的共享数据容量，FPGA parity 容量不计入该值，详见 [共享 RAM 映射](../docs/shared_ram_mapping.md)。

IA=1 只支持紧凑输入；S16 行需要两个独立 bank。紧凑和宽格式的 16×16 IA 分块分别占用 256 B、512 B，R 上限按当前 IA 字节数除以两个分块的字节数计算。8 KiB bank 分配 IA=4 时，紧凑格式的 IA 容量允许 R=64，宽格式允许 R=32。非最终 RAW32 PS 行需要至少四个 PS bank，严格 S24、S16 上限分别需要至少三个、两个 PS bank。软件先查询能力和容量，再计算 bank 分配、R/W 及四个工作组参数。层间更改分配会重新初始化相关存储状态。

S8 输出 FIFO 可容纳整个 IA 行组。默认 16 个 PS frame 下，2、4 KiB bank 构建的 `MATRIX_OUTPUT_BANKS[15:0]` 为 32，8 KiB bank 构建为 64；默认 `MATRIX_OUTPUT_BANKS[31:16]` 为 4。S16 输出任务还需满足该输出 bank 数对应的 R 限制。

`dsa_set_ps_force_raw()` 在模型 Prepare 之前选择运行时策略。准备好的任务保存 `PS_CONTROL` 和 IA bank 数，执行时随其他配置提交。同一硬件的 RAW32 与压缩性能比较应分别准备任务，并保持输入、时钟、AXI 设置和总物理容量相同。
