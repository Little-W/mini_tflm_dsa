# Vector Compute Engine

Vector Compute Engine（VCE，向量计算引擎）通过描述符和 MMIO 接收完整算子任务。
DW 卷积、池化、量化 Add 和基础向量运算共用 PE、DMA、累计状态和写回接口。
完整 NPU 使用 16×16 脉动阵列和 8 个 VCE PE。AXI 数据接口支持 32 位和 64 位，
FPGA 配置默认使用 64 位。VCE 与矩阵路径共用 DMA 和窗口缓存。

## 支持范围

| 操作 | 编码 | 输入 | 输出 | 主要限制 |
|---|---:|---|---|---|
| `DW_S8` | 0 | INT8 输入和权重，INT32 偏置 | INT8 | 通道倍率 1，核面积不超过 49 |
| `AVGPOOL_S8` | 1 | INT8 | INT8 | 窗口面积不超过 256 |
| `MAXPOOL_S8` | 2 | INT8 | INT8 | 窗口面积不超过 256 |
| `MINPOOL_S8` | 3 | INT8 | INT8 | 窗口面积不超过 256 |
| `VEC_SUM` | 4 | INT8 或 INT16 | 一个 INT32 | 按向量长度分段累计 |
| `VEC_MAX` | 5 | INT8 或 INT16 | 一个 INT32 | 比较有效元素 |
| `VEC_MIN` | 6 | INT8 或 INT16 | 一个 INT32 | 比较有效元素 |
| `VEC_DOT` | 7 | 两个同类型向量 | 一个 INT32 | 逐元素乘法后求和 |
| `VEC_HADAMARD` | 8 | 两个同类型向量 | INT32 向量 | 逐元素乘法 |
| `ADD_S8` | 9 | 两个 INT8 向量 | INT8 向量 | 独立输入量化和输出量化 |
| `SOFTMAX_S8` | 10 | INT8 向量和 Q31 指数查找表 | INT8 向量 | 长度不超过 `TILE` |

图像采用 NHWC 布局，DW 权重采用 `[Kh, Kw, C]`。图像命令处理一个 batch，
NMSIS 驱动依次提交多个 batch。等形状 Add 将连续张量展平为向量，保留原始元素顺序。
广播 Add 由 TFLM 的通用软件内核执行。SUM 和 DOT 的 32 位累计结果按 `2^32`
取模，MAX 和 MIN 使用有符号比较。

软件接口的 DW 上限为 `DSA_DW_MAX_TAPS=49`，池化上限为
`DSA_POOL_MAX_TAPS=256`。默认硬件 `POOL_MAX_TAPS=256` 覆盖 DS-CNN 的
25×5 平均池化、ResNet-8 的 8×8 平均池化以及 16×16 窗口。池化根据窗口面积和有效输入数量控制累计，
继续使用相同的 PE 和累计寄存器，DW 权重缓冲按 49 个位置分配。

驱动同时检查软件上限和设备公布的容量。设备设置 `CAPS[4]` 时，池化容量从
`NPU_REG_POOL_MAX_TAPS` 读取；其他设备使用 `CAPS[23:16]` 公布的窗口上限。
合法池化配置超出设备能力时，NMSIS 在提交任务前选择软件实现。池化使用相同的输入、
输出量化比例和零点，描述符的输入、输出 offset 均为零，膨胀系数为 1。
每个输出窗口须包含至少一个有效输入元素。

## 计算与数据复用

### 共享计算单元

每个 `vector_pe` 包含一个 16×16 位乘法器、32 位累计逻辑以及最大值和最小值比较逻辑。
`TILE` 决定每段暂存元素数，`PE_COUNT` 决定每个计算周期处理的元素数。
默认 `TILE=16`、`PE_COUNT=8`，完整通道段分两组计算，尾部仅处理有效元素。
每组依次完成操作数寄存和结果写入，将输入选择与乘加分在不同周期。

Add、DW 重新量化、平均池化和 Softmax 共用 `vector_scalar_multiplier`。
该模块由四个固定的 16 位分积构成，保留完整的有符号 64 位乘积。
输入在第一个时钟边沿寄存分积，第二个边沿寄存完整结果，消费者在第三个边沿接收结果；
流水线每周期能够接收一组输入。

Add 的两个输入分别重新量化，再对它们的和执行输出重新量化。
三个量化阶段顺序复用标量乘法器和舍入通路。DW 按通道段装载权重、偏置和逐通道量化参数，
在该通道段的所有输出位置之间复用。平均池化采用固定倒数系数与精确余数修正，
分母为二的幂时使用移位舍入。

Add 使用加载完成、舍入完成和求和阶段提前寄存下一次乘法的操作数，三个量化阶段共用该寄存器。INT8 输入与合法 offset 相加后采用有符号 9 位表示，再扩展到共享乘法器的输入位宽。输入选择和 offset 加法在乘法之前完成，量化计算仍使用完整的 INT32 操作数和 INT64 乘积。

平均池化根据最大窗口面积确定求和位宽，并在量化初始化阶段寄存绝对值。倒数乘法、乘积校验、余数计算、商修正以及最近偶数舍入分别执行。配置检查使用两个独立的 16 位乘积组成 32×16 位结果，乘积寄存和结果组合分处两个阶段。

二的幂窗口平均值使用移位后的向下取整值并行检查激活范围，同时计算最近偶数舍入的增量。下界之外取激活下限，上界处及其上方取激活上限，区间内部使用舍入结果。比较与增量计算同时进行。

Softmax 支持最多 256 个元素。合法指数数据使输出右移量处于 54 至 62，因此输出缩放先固定移位 48 位，再使用 18 位的商、保护位和舍弃位归并通路完成剩余移位及最近偶数舍入。

Softmax 在指数响应边沿保存整数部分和舍入进位，下一边沿更新累计结果。
七系列 FPGA 使用一个 `DSP48E1`，其中 `C`、`CARRYIN` 和 `P` 寄存器分别保存
指数数据、舍入进位和累计值。最后一个指数响应之后执行一个累加完成周期，
随后开始归一化。任务初始化清除累计值和待处理有效标志。

倒数迭代接收乘积时保存有符号商及最近偶数舍入增量；输出缩放接收乘积时保存
18 位商、保护位和舍弃位信息。剩余舍入在后续阶段完成，外部共享乘法器的
两周期接收安排与逐元素输出顺序保持一致。

### 模块组织

| 模块 | 功能 |
| --- | --- |
| `vector_config_check` | 分阶段检查描述符、几何尺寸、数据长度和访问范围 |
| `vector_pe` | 有符号乘加、求和、最大值、最小值与逐元素乘法 |
| `vector_scalar_multiplier` | 两级寄存、每拍一组的精确 INT32×INT32 乘法 |
| `vector_round_shift` | 六级固定移位、舍弃位归并与最近偶数舍入，中间设置寄存阶段 |
| `vector_softmax` | 指数查表、累计、定点倒数迭代和输出缩放 |
| `vector_writeback` | 保存输出事务元数据、打包字节并等待写响应 |

### DW 与窗口池化

VCE 使用 `conv_im2col_frontend`、DMA 内的共享窗口缓存及有序窗口描述队列。
缓存容量由 `IM2COL_CACHE_BYTES` 配置，默认 4 KiB。相邻窗口使用同一缓存保存的输入字。
输入零点在前端扩展为 INT16 时修正。

VCE 的输入暂存包含 `2*TILE` 个 INT16 元素。有效通道数不超过 `TILE/2` 时，
该暂存划分为四个区域；其他通道段使用两个区域。窗口描述的标签标识目标区域，
预留标志与就绪标志分别表示在途请求及已经接收完成的数据。
非对齐窗口可以分成不足四个元素的小段，四路旋转结构将其映射到固定的存储银行。

新配置在已接受的事务完成后生效。窗口错误按原始标签返回终止响应，主状态机继续接收在途响应，
并等待已经提交的输出写入完成。任务结束时，输入区域和写事务均已释放。

### 全局池化

当输出为 1×1、窗口覆盖整个输入、padding 为零且膨胀系数为 1 时，
池化按像素顺序分批读取输入，随后逐像素送入共享 PE 和累计寄存器。
一个输入批次最多承载 `2*TILE` 个元素，默认值为 32。
通道较多时，线性 DMA 使用像素步长选取当前通道段。

该方式用于 25×5 和 8×8 平均池化，并与小窗口池化共用运算、舍入和写回逻辑。
大窗口无需按整个窗口建立输入缓存。有效元素总数用于最终平均值计算，
读入一个批次后即可累计并复用输入缓冲。

### DMA 与写回

VCE 与输入、权重、量化参数和矩阵结果客户端共用 `axi_dual_block_dma`。
参数读取和缓存输入读取分别配置允许访问的地址区间，切换前等待当前事务完成。
线性 AXI 读取按物理地址的 4 KiB 边界及 256 拍限制分割。
写通路通过 `axi_write_page_guard` 保持 AXI 突发符合 4 KiB 限制。

INT8 输入、Add 输入和 INT8 输出允许任意字节地址。输出字节通过 `WSTRB` 控制，
不足一个字的结果不会改变相邻字节。INT16 输入须按 2 字节存放，INT32 参数和输出须按
4 字节存放。驱动要求基址非零，并且每个分配区间的末尾地址 `base + bytes`
严格小于 `2^32`。

总线背压时请求内容保持稳定。DMA 返回错误后，引擎等待已提交事务完成，再报告任务错误。

写回控制器仅保存地址、长度、格式和字节偏移，结果保留在主单元的单个结果区域。
写回数据按总线字节通道分组，通过固定通道选择和分级旋转形成 AXI 数据；32 位和 64 位总线分别使用对应的两级和三级字节旋转。
接收写描述后，结果区域保持稳定，直到写响应完成。下一窗口的输入预取和累计运算
可以在此前结果写回期间继续；重新量化等待结果区域可以使用后开始。
DW 重新量化每周期接收一个累加值及其逐通道系数，流水线保留通道索引和移位参数。
移位参数装载时转为六位右移量，原始参数仍按完整 INT32 数值检查合法范围。


## 最近偶数舍入

本节说明本项目 RV32IM 标量软件和当前标准核心硬件的数值规则。
INT8 Conv、DW、FC、Add、AvgPool 以及 TFLM Softmax 整数运算使用
round to nearest, ties to even（RNE）。取距离原值最近的整数；
恰好位于两个整数中间时，选择偶数。例如 `0.5→0`、`1.5→2`、`2.5→2`，
`−0.5→0`、`−1.5→−2`、`−2.5→−2`。

### INT8 重新量化

设累加值为 `a`，Q31 系数为 `m`，指数为 `s`：

```text
r = RNE((int64(a) * m) / 2^(31 - s))
y = clamp(r + output_offset, activation_min, activation_max)
```

INT32 累加值与 Q31 系数的乘积保留完整 64 位，最终移位执行一次舍入。
硬件在增加输出 offset 和激活裁剪前保留 INT64 结果。RV32IM 标量软件先将舍入结果
饱和为 INT32，再以安全加法处理输出 offset 并裁剪到 INT8；在上述 INT8 输出范围内，
两种实现得到相同结果。系数为非负 INT32，指数范围为 `[-31, 30]`。
DW、Conv 和 FC 使用此规则。

### 量化 Add

```text
a = (input1 + input1_offset) * 2^left_shift
b = (input2 + input2_offset) * 2^left_shift
u = RNE(a * input1_multiplier / 2^(31 - input1_shift))
v = RNE(b * input2_multiplier / 2^(31 - input2_shift))
r = RNE((u + v) * output_multiplier / 2^(31 - output_shift))
y = clamp(r + output_offset, activation_min, activation_max)
```

这三个舍入分别执行。输入 offset 范围为 `[-127, 128]`，输出 offset 范围为
`[-128, 127]`；`left_shift` 范围为 `[0, 22]`，输入指数范围为 `[-31, 0]`，
输出指数范围为 `[-31, 30]`。三个系数均为非负 INT32。

两个只读输入可以彼此重叠。硬件输出须与两个输入的完整区间互不相交。
NMSIS 的 `riscv_elementwise_add_s8()` 支持软件原位计算：输出与每个输入之间须满足
地址完全相同或区间互不相交。输出与任一输入部分相交时返回
`RISCV_NMSIS_NN_ARG_ERROR`，不访问张量、不提交 DMA。

硬件描述符要求向量长度大于零。NMSIS 入口对长度为零且量化参数合法的调用直接返回
成功，不访问张量和设备。能力不足时在 START 前使用软件计算；设备忙、任务超时或
硬件报告错误时返回 `RISCV_NMSIS_NN_NO_IMPL_ERROR`。

### 平均池化

平均值为 `RNE(sum / valid_count)`，padding 不参与求和或计数。
令 `q` 为向零截断的整数商，`r = sum - q * valid_count`。
当 `abs(r) > valid_count - abs(r)`，或两者相等且 `q` 为奇数时，将 `q`
增加 `sign(sum)`；其他情况下保留 `q`。窗口至少包含一个有效输入元素，
完成舍入后执行激活裁剪。

NMSIS 的 INT64 累加输入接口使用 reduced-Q15 系数。`REDUCE_MULTIPLIER(m)`
计算 `RNE(m / 2^16)` 并将上限限制为 32767；随后计算
`RNE(accumulator * reduced_multiplier / 2^(15-shift))`，最后饱和为 INT32。
该接口的累加值范围为 `[-2^47, 2^47-1]`，指数范围为 `[-31, 7]`。
TFLM 的 INT64 重载接收 Q31 系数，使用多字整数乘积保留完整精度，最终执行一次 RNE。

量化系数生成也采用最近偶数舍入。INT8 Softmax 的输入缩放、固定点指数近似中的乘法、
累计值缩放、倒数迭代中的半和与乘法均使用 RNE；最终倒数与指数值的乘积同输出移位
合并为一次 RNE，随后增加输出零点并裁剪。

## 软件接口与寄存器

公开接口位于 `drivers/dsa_vector.h`，实现位于 `drivers/dsa_vector_impl.h`：

```c
void dsa_vector_config_init(dsa_vector_config_t *config);
uint32_t dsa_vector_capabilities(void);
uint32_t dsa_vector_validate(const dsa_vector_config_t *config);
uint32_t dsa_vector_execute(const dsa_vector_config_t *config);
```

`validate()` 不访问 MMIO 或张量内存，检查形状、地址区间、输出覆盖以及 Add 的标量
量化参数。DW 的逐通道量化数组由硬件通过 DMA 装载。
`execute()` 检查能力、写入寄存器、启动任务并等待完成。
NMSIS 的 DW、平均池化、最大池化和 Add 入口接入该接口。

TFLM 的通用 Add 内核保留软件实现。启用 `NMSIS_NN` 和 `DSA_NN_VECTOR_ENABLE`
后，无广播 INT8 Add 调用 `riscv_add_s8_try_dsa()` 尝试硬件执行；运行时
`DSA_NN_ACCEL_ADD` 控制该选择。软件编译配置、广播及硬件能力不满足时使用
TFLM 的通用软件 Add。

`CTRL[8]` 选择 VCE，`CTRL[6]` 选择 Conv，两者互斥。
基础向量与图像操作使用编码 0 至 8，Add 使用编码 9，Softmax 使用编码 10。

| 偏移 | C 标识符 | 用途 |
|---|---|---|
| `0x0b0` | `NPU_REG_VECTOR_OP` | 操作和 INT16 标志 |
| `0x0b4` | `NPU_REG_VECTOR_LENGTH` | 向量元素数 |
| `0x0b8` | `NPU_REG_VECTOR_CAPS` | 能力、PE 数、DW 核面积上限、版本 |
| `0x0bc` | `NPU_REG_VECTOR_CYCLES` | 保留，读取零 |
| `0x0c0` | `NPU_REG_VECTOR_COMPUTE` | 保留，读取零 |
| `0x0c4` | `NPU_REG_VECTOR_DMA_WAIT` | 保留，读取零 |
| `0x0c8` | `NPU_REG_POOL_MAX_TAPS` | 只读池化窗口上限，默认 256 |
| `0x0cc` | `NPU_REG_VECTOR_ADD_INPUT1_MULT` | 第一个输入的 Q31 系数 |
| `0x0d0` | `NPU_REG_VECTOR_ADD_INPUT1_SHIFT` | 第一个输入的指数 |
| `0x0d4` | `NPU_REG_VECTOR_ADD_INPUT2_MULT` | 第二个输入的 Q31 系数 |
| `0x0d8` | `NPU_REG_VECTOR_ADD_INPUT2_SHIFT` | 第二个输入的指数 |
| `0x0dc` | `NPU_REG_VECTOR_ADD_LEFT_SHIFT` | 两个输入的共同左移量 |

Add 复用公共输入、输出、offset、输出 multiplier、输出 shift 和激活范围寄存器。
`CAPS[5]` 表示 INT8 Add，`CAPS[4]` 表示设备提供池化窗口上限寄存器；
低四位继续表示 DW、池化和 INT8/INT16 基础向量能力。
`CAPS[15:8]` 为 PE 数，`CAPS[23:16]` 为 DW 核面积上限，最高字节为版本 1。
默认 8 PE 返回 `0x0131083f`，4 PE 返回 `0x0131043f`。

`drivers/dsa_dw_pool.h`、`drivers/dsa_dw_pool_impl.h` 和
`drivers/tflm/NMSIS/NN/Include/riscv_dw_pool_acc.h` 提供源代码兼容定义。
`dsa_dw_pool_config_t`、`dsa_dw_pool_operation_t`、四个 `dsa_dw_pool_*` 函数、
原寄存器名称和能力宏映射到 VCE 接口；`DSA_DW_POOL_MAX_TAPS` 保持为 49。
仅定义 `DSA_NN_DW_POOL_ENABLE` 时，该值用于设置 `DSA_NN_VECTOR_ENABLE`；
同时指定两者时，新名称优先。
顶层保留 `ENABLE_DW_POOL`、`DW_PE_COUNT`，并提供
`ENABLE_VECTOR_ENGINE` 与 `VECTOR_PE_COUNT`。
标准核心支持 VCE；不支持该单元的构建返回零能力，软件在启动前选择适用实现。

## 验证与模型测试

直接 RTL 测试涵盖通道尾部、不同 PE 数、3×3 DW、非缓存核形状、padding、步长、
量化 Add、大小窗口池化、未按字存放的地址、跨 4 KiB 读取和随机等待。
生产 C 与 RTL 协同测试通过 AXI-Lite 提交真实任务，并在硬件执行期间禁止 CPU 访问
测试输入和输出，确认计算由 RTL 完成。

完整模型测试运行 CNN、MobileNetV1、DS-CNN 和 ResNet-8。
软件和硬件版本使用相同模型、真实输入、CPU、外部 RAM 容量、时序和优化等级。
完整推理计时与逐层输出记录分别构建，逐层结果与已记录的 RNE 参考张量比较。
测试记录每个算子的周期、占比、硬件任务、实际读写字节及错误状态。

运行方式见 [`test/model_benchmark/README.md`](../test/model_benchmark/README.md)。
