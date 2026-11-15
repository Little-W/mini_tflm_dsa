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
| 8 | `NPU_CTRL_DW_POOL` | 使用 DW、池化或向量模式，与 bit 6 互斥 |

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

设公开 GEMM 形状为 `C[M,N] = A[M,K] × B[K,N]`。本项目寄存器命名为 `REG_K=M`（输出行数）、`REG_N=K`（归约维）、`REG_M=N`（输出列数）。WS 内部流行／列对应 M／N；IS 对应 N／M。计算分组时使用内部流维度以及外部计算得到的最终 R、W，包括容量裁剪、支持尺寸取整和 IS 调整。ABI 2 的 R/W 寄存器必须写入非零最终值，支持二次幂及 25，且不能超过对应硬件容量；RTL 检查参数合法性。软件函数仍允许以 0 表示请求自动选择，然后返回非零最终值。

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
权重直接使用 OHWI，`RHS_STRIDE_B=N`；无需转置或运行时打包。
`DST_STRIDE_B` 为完整输出 Cout，组地址只加当前组的通道起点。
`LHS_STRIDE_B=roundup(N,SIZE)×2` 供原 IA 调度使用；硬件直接取得 tile 的
p0/q0，外部存储器中不分配或读取展开矩阵。WS 由 ia_loader 提交 im2col 请求，
IS 由 kernel_loader 提交；两者均从 block DMA 获取相同的普通矩阵块返回接口。
IS 的驻留排列和输出转置继续由原 kernel buffer / 写回路径处理。

`dsa_conv_s8_execute()` 每次处理一 batch 的一个通道组，字段逐项写 MMIO。
`dsa_conv_s8_config_t.dataflow_mode` 为 0 时选择 WS，为 1 时选择 IS；零初始化
保持 WS 默认。两种模式的公开 K/N/M、地址和张量布局相同，分组参数根据模式
调用原生产 planner 计算。标准 NMSIS 分发入口仍默认选择 WS。
NMSIS 公共入口在任何软件 im2col 或 scratch 检查之前分发，CPU 对 batch/group
仅循环配置命令。所有受支持路径都不读取激活/权重、不展开窗口，也不执行 Conv MAC。
CPU 只检查量化和 bias 数组，以保守数值界排除可能溢出的配置。

当前软件范围：NHWC s8、OHWI s8、s32 bias/累加、逐通道双舍入、s8 输出，
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

验证入口与证据分类见 `test/conv_driver/README.md`。寄存器/CPU 路径测试与实际
RTL 端到端输出对比是两项独立验证，不能用前者替代后者。

## DW、池化与向量扩展

`CTRL[8]=1` 选择 `dw_pool_engine`。操作由 `DW_POOL_OP` 指定，图像几何复用
Conv 寄存器，输入、权重、输出、bias、multiplier 和 shift 复用公共地址寄存器。
输入基地址同时写入 `LHS_BASE` 和 `CONV_INPUT_BASE`。
DW 采用 `[Kh, Kw, C]` 权重、NHWC 输入输出和逐通道量化；每条命令处理一个 batch。
向量模式使用 `LHS_BASE`、`RHS_BASE` 和 `DST_BASE`，长度由专用寄存器给出。

| Byte offset | Word offset | Name | Access | 字段 |
|---:|---:|---|---|---|
| `0x0b0` | `0x02c` | `DW_POOL_OP` | RW | bits 3:0 为操作，bit 8 为 s16 向量输入 |
| `0x0b4` | `0x02d` | `DW_POOL_LENGTH` | RW | 向量元素数，大于 0 |
| `0x0b8` | `0x02e` | `DW_POOL_CAPS` | RO | 能力、PE 数量、最大窗口面积和扩展版本 |
| `0x0bc` | `0x02f` | `DW_POOL_CYCLES` | RO | 本次引擎任务周期 |
| `0x0c0` | `0x030` | `DW_POOL_COMPUTE` | RO | PE 执行周期 |
| `0x0c4` | `0x031` | `DW_POOL_DMA_WAIT` | RO | 读取、窗口返回、写回及相关等待周期 |

操作编码：`0=DW_S8`，`1=AVGPOOL_S8`，`2=MAXPOOL_S8`，`3=MINPOOL_S8`，
`4=SUM`，`5=MAX`，`6=MIN`，`7=DOT`，`8=HADAMARD`。
向量输入可为 s8 或 s16；归约结果为一个 s32，Hadamard 输出为 s32 向量。
图像模式使用 s8 输入输出，`DW_POOL_OP[8]=0`，`CTRL[8]=1`。

`DW_POOL_CAPS` 的 bits 0/1/2/3 分别表示 DW s8、池化 s8、向量 s8、向量 s16；
bits 15:8 为 PE 数量，bits 23:16 为最大窗口面积，bits 31:24 为版本 1。
默认 8 PE、49 个窗口位置返回 `0x0131080f`；4 PE 返回 `0x0131040f`。
设备不支持该扩展时返回 0。软件先检查设备 ID、配置 ABI 2 和扩展版本，再启动任务。
统计寄存器在引擎接受 START 时清零。顶层拒绝的双模式命令不启动引擎，统计值
保留为上一次引擎任务的结果。

任务期间配置寄存器不接受更新。完成、中断和 DONE 写 1 清除沿用公共状态接口。
配置无效时报告错误码 `01`；DMA 响应异常或读取后的量化参数无效时报告 `10`。
同一任务同时设置 Conv 与 DW 模式将被拒绝。错误完成前，已提交的 DMA 事务会结束。

`dsa_dw_pool_validate()` 不访问 MMIO 或张量内存；`dsa_dw_pool_execute()` 完成
检查、配置和等待。`DSA_DW_POOL_TIMEOUT` 表示状态寄存器轮询次数，默认继承
`DSA_MATMUL_TIMEOUT`。超时返回时设备仍可能执行，缓冲区再次使用前应由平台确认
设备停止或完成复位。支持范围和完整测试结果见 [DW 引擎说明](../docs/dw_pool_engine.md)。
