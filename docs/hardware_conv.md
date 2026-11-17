# 普通 s8 Conv 的硬件 im2col：集成与验证

**当前架构入口：** [block_dma 统一矩阵与 im2col 接口](block_dma_im2col.md)。
im2col、原图 cache、读范围保护和读响应复用现在都位于共享 DMA 内；WS 的
IA loader 与 IS 的 kernel loader 使用同一矩阵返回合同。本文保留初始集成和
容量实验的历史结果与设计解释。生成向量与本轮验证见 [源码交付说明](conv_source_only.md)，
当前 DMA 重构的源码 / 周期 / 验证以新设计说明和
[`test/conv_dma`](../test/conv_dma/README.md) 为准。

## 交付范围与固定基线

本次在原工程中接通了普通 NMSIS s8 Conv 的原始 NHWC 输入、窗口生成、输入缓存、
原 IA / kernel tile RAM、原脉动乘加、部分和、bias、逐通道量化和 NHWC 写回。受支持调用直接
提交原输入及 OHWI 权重地址，CPU 只准备命令、轮询和检查少量数值参数，不生成
外部 im2col 矩阵。原 PE、脉动互连及量化算法没有修改。

- 上游仓库：`https://github.com/Little-W/mini_tflm_dsa`
- 初始实验基线：`e8a73373009064026fd0be1cbf3af6870d592ebb`；当前完整补丁固定基线为
  `148964d180f52cb852c5a7e3d5c89773fa0a8ea5`。
- 仿真器：官方源码构建 Verilator 5.054，固定源码 commit
  `e4c94116fafb093ce153c9d2f295d3b1f0725bab`。
- RAM 推断：Yosys 0.71，commit `b4c586fd3`，通过 YoWASP 运行。

本文保留历史实验的结论与覆盖范围。当前补丁仅包含源码与文档，历史日志、
失败快照、向量和构建报告不再随补丁交付。所有当前测试从生成规则现场准备数据，
方法及本次重新执行范围见 [源码交付说明](conv_source_only.md)。

当前标准配置使用 **4 KiB 共享窗口缓存**，参数为 128 sets、2 ways、16 B line、
`CONV_CACHE_POLICY=3`，同时服务 Conv 和 DW。`IM2COL_CACHE_BYTES` 可在配置文件
中选择 512 B～64 KiB，组数按数据容量自动计算。缓存容量、卷积尺寸提示和能力寄存器
见 [im2col 缓存容量配置](im2col_cache_configuration.md)。统一 NPU 路径支持 PS 压缩和共享
IA/PS bank，详见 [硬件架构](architecture.md) 与 [容量说明](capacity.md)。

本文的容量实验采用固定实验版本：小层容量与十层六模式表来自
`629a39a4e0497036ab66942ca8b58b13d5d2ceca`；1 KiB、策略 2 的实验及其适用条件见
[卷积专用替换设计与实测](conv_replacement.md)。后文对应的缓存和 IA 结构说明均使用这些实验参数。

## 实际数据路径

WS 的 IA controller 或 IS 的 kernel controller 直接输出当前 tile 的
`p0/q0/group/rows/slot` 描述符，请求共享 DMA；没有通过外部 im2col 矩阵地址
反推正常执行路径。DMA 内的窗口前端按下面的关系生成地址：

```text
p = oy * output_w + ox
q = (ky * kernel_w + kx) * group_c + channel_in_group
iy = oy * stride_h - pad_top  + ky * dilation_h
ix = ox * stride_w - pad_left + kx * dilation_w
addr = input_base + (iy * input_w + ix) * input_c
       + group_offset + channel_in_group
```

越界窗口位置与归约尾部直接产生校正后的零；有效 s8 原始输入符号扩展后加上
`input_offset`，以普通矩阵元素流写入当前 owner 的原 tile buffer。原 tile 内仍会出现展开后的重复元素，
以保持原计算数据流；复用发生在外部访存之前。

输入读取与原权重 / bias / 量化参数读取经过同一个共享 DMA 仲裁。Conv 模式下，返回响应依据
已锁存的请求归属分发；阻塞时地址保持稳定。GEMM 模式保留直接旁路，既有多请求
行为由机械迁移的原线性引擎保留。DMA 内的整字权重读取另经过范围保护器，在
首尾无效 lane 和 4 KiB 边界处精确拆分；无效 lane 本地补零。

真实 SoC RAM 原先没有保存 ARSIZE，连续窄读会错误地逐 word 递增。本次补齐
ARSIZE / burst 描述符、正确 byte lane、INCR / FIXED 地址推进、RAM 容量及
4 KiB 检查，保留原完整 word 响应流水。详见
[SoC RAM 回归](../test/conv_soc_ram/README.md)。

## 卷积核尺寸及运行时配置

卷积核高、宽支持每条任务动态配置，矩形核也适用。它们不绑定为 1×1、3×3 或 5×5，
改变核大小不要求重编译 RTL。

| 参数或约束 | 当前集成支持范围 |
|---|---|
| `kernel_h`、`kernel_w` | 分别为 16 位无符号非零字段：1～65535 |
| 实际 NMSIS / C 驱动归约长度 | `kernel_h * kernel_w * group_c <= 65535` |
| 输入 / 输出 H、W，输入 / 当前组通道数 | 非零 16 位字段，并继续检查乘积、地址跨度和 tiling 可行性 |
| `stride_h/w`、`dilation_h/w` | 分别动态配置，1～65535 |
| `pad_top`、`pad_left` | 动态配置，0～65535；输出 H/W 显式给出 |
| `input_offset` | s8 合同：−127～128 |
| 地址 | 32 位总线地址；完整分配区间不允许溢出，当前合同要求 exclusive end 小于 2³² |
| 输入 / 权重 / 输出 | s8 NHWC / s8 OHWI / s8 NHWC |
| 累加 / bias / 量化 | s32，逐通道 multiplier / shift，使用最近偶数舍入；NMSIS 入口检查保守累加范围，直接调用低层驱动需满足相同的数值要求 |
| 计算模式 | 标准 NPU 的 WS / IS；接收原图输入的 loader 获得已加 offset 的 s16 矩阵 |
| batch / group | CPU 按 batch 和通道组提交多条硬件命令，每条任务执行完整空间卷积 |

例如 `group_c=64` 时，31×31 的归约长度为 61504，满足上述长度条件；32×32 为
65536，超过当前驱动上限。这个例子只说明长度约束，实际执行还必须满足地址、
输出布局、数值与存储资源检查；并未用仿真穷举这个尺寸范围。

`CONV_KERNEL_HW` 位于字节偏移 `0x084`：低 16 位为高，高 16 位为宽。`CTRL[6]`
启用硬件 Conv，`CTRL[7]` 控制输入缓存旁路。任务开始锁存配置；busy 期间配置写入
和重复 START 返回 AXI-Lite SLVERR。任务结束后可以设置另一种核大小、stride、
dilation、padding 和输入地址。完整寄存器布局见
[寄存器 ABI](../drivers/registers_v2.md)。

标准 generic、wrapper、1×1、fast 1×1、1×N 入口及对应 `_acc` 调用统一在软件
im2col / scratch 检查之前尝试硬件。合法但超出硬件支持范围的调用转入原软件路径；
参数本身非法则返回参数错误。busy 在 START 前拒绝；启动后的硬件错误和 timeout
不触发可能与仍活动 DMA 竞争的软件重试。统一 PS 压缩路径支持普通 s8 Conv。
禁用逐通道量化的配置、完整 s16 Conv 和转置卷积不属于此入口；DW 由 VCE 执行。

## 卷积窗口重复数据的复用语义

输入复用由以下单元完成：

1. **一个 32 位字保持寄存器。** 同一任务内再次使用当前字，直接取 lane，连缓存
   请求也不发送。该寄存器跨窗口、跨 tile 保留，cache bypass 模式下仍然有效。
2. **实验配置的 1 KiB 原始输入地址缓存。** 32 sets、2 ways、16 字节 line；适用几何
   使用未来访问预测与选择性存入，不适用的任务使用原 LRU。数据存储为一块
   1R1W RAM。标签命中只从内部 RAM 返回数据，不进入
   AXI 填充状态。缓存为阻塞式，一次 miss 完成前不接收第二个请求；随后对同一
   驻留 line 的访问命中，不会并发生成第二次填充。
3. **16 B 临时 line 缓冲。** 对新策略决定不长期保留的数据，提供当前连续四个
   word，避免为了返回当前数据覆盖更值得保留的驻留 line。换到不同 line 后失效。

缓存和保持寄存器没有按窗口或 tile 清空，所以相邻窗口的重叠输入、归约分块及
输出通道重放可以复用。新硬件任务配置时失效，确保同地址换内容仍读到新值。
运行期间输入必须保持稳定；有非一致性 CPU cache 的平台需要调用方完成相应维护。

### 与原 IA 的 A 分块缓存容量比较

标准 IA Loader 具有 `SIZE` 个独立的 1R1W bank，每个 bank 的逻辑深度是
`IA_CACHE_BLOCKS * SIZE`，宽度是 `DATA_WIDTH`。默认四个 slot、s16 物理数据位宽时：

| SIZE | 单个 A tile | 实验 IA 的四个 tile | 4 KiB / IA | 1 KiB 主数据 / IA |
|---:|---:|---:|---:|---:|
| 4 | 32 B | 128 B | 32 倍 | 8 倍 |
| 8 | 128 B | 512 B | 8 倍 | 2 倍 |
| 16 | 512 B | 2048 B | 2 倍 | 0.5 倍 |

一般逻辑容量为 `IA_CACHE_BLOCKS * SIZE * SIZE * DATA_WIDTH / 8`。当前 RAM
wrapper 的深度实际为 `2^ceil(log2(IA_CACHE_BLOCKS * SIZE))`，非二次幂配置还要
计入向上取整；FPGA / ASIC 宏分配的实际面积另外取决于工艺映射。运行时输入 s8
不会自动将 IA 物理 RAM 从 s16 缩小一半。

原 IA 保存的是已经展开、加过 input_offset 的 A tile，支持矩阵乘法输出通道方向的
重复发送；独立输入缓存保存原始地址的 s8 字节，消除不同窗口 / tile 形成过程的重复
外读。默认 `R=2` 时，四个 IA slot 可同时容纳当前两个 tile 和预取的两个 tile。

4 KiB LRU 实验还需另加 tag、valid、LRU 数组共 720 B。1 KiB 几何策略实验的
主数据、tag / valid / LRU、32 位 next-use 表、临时数据和临时 tag / valid 合计
约 1496 B；替换策略新增共享状态另约 103 B，此次 DMA 命令状态另行审计，完整算术面积尚未测量。容量通过 `npu_top` 或
`npu_axil_top` 的 `CONV_CACHE_SETS/WAYS/LINE_BYTES` 在 elaboration / 综合时设置。
`CONV_CACHE_POLICY=0/1/2` 分别选择旧 LRU、未来访问替换、未来访问替换加 XOR
索引。本文几何替换实验使用策略 2；当前共享窗口实现使用策略 3。
运行时 `bypass_cache` 改变读取策略，不会把已经综合的 RAM 面积消除。

### LRU 基线：真实 NPU 的容量对照

保持 `SIZE=16`、2 路、16 B line、IA 四个 slot 与固定 AXI 等待条件，只改变 sets。
输入为 12×12×16，共 2304 B；核 3×3，stride=1、padding=1、Cout=17。每一档
执行真实 NPU，并逐元素核对结果、逐地址核对外读：

| 数据容量 | sets | tag / valid / LRU | 实际输入外读 | 重复读取 | miss | 完成周期 |
|---:|---:|---:|---:|---:|---:|---:|
| 256 B | 8 | 53 B | 18039 B | 15735 B | 1129 | 84102 |
| 512 B | 16 | 102 B | 2304 B | 0 B | 145 | 71555 |
| 1024 B | 32 | 196 B | 2304 B | 0 B | 145 | 71555 |
| 2048 B | 64 | 376 B | 2304 B | 0 B | 145 | 71555 |
| 4096 B | 128 | 720 B | 2304 B | 0 B | 145 | 71555 |

同一轮额外运行 75 B 的小输入层，五档均只读 75 B、5 次 miss、3976 周期。
这两个层中，4 KiB 没有比 512 B 带来更多收益；512 B 是较大层的**已测最小零重复**
配置，256 B 对该层出现明显冲突 / 容量重读。不能由两层推出所有网络的最优容量。
这些是逻辑存储位和周期 / AXI 流量结果，尚无工艺映射后的面积与功耗结论。完整
数据见 [复现入口](../test/conv_npu/capacity.py)。

### LRU 基线：真实 CNN 层尺寸与生产默认分块

进一步直接解析仓库已有的 MNIST、手势识别、Person Detection 和 MobileNetV2
四个 TFLite 文件，从 63 个普通 INT8 Conv 中选取 10 层，保持原始输入 / 输出
HWC、kernel、stride、dilation 与四边 padding。通过实际 builtin opcode 区分
普通 Conv 和 depthwise，未将后者计入支持范围。模型路径、SHA-256、算子索引和
完整形状见 [模型清单](../test/conv_models/README.md)。

各层采用相同固定种子的合成输入、权重、bias 与量化参数，逐元素对照直接 C
卷积及仓库真实 NMSIS 量化参考。这里验证真实模型**尺寸**下的正确性和访存，
没有使用训练权重和真实样本执行完整网络。MobileNetV2 最后一项保留 Cout=576
以及完整的 112896 B 输出，没有为测试内存上限缩小层。

主结果使用实际 `gempact_plan_capacity` 的生产自动选择：requested R/W=0/0，
SIZE=16、IA 四个 slot、16 个 PS frame、WS、逐通道量化。先执行的显式 R/W=2/2
压力对照覆盖 10 层 × 6 模式，共 60 条实际 RTL 命令；其中 4 层与自动选择不同，
追加执行全部 24 条。其余 6 层的全部 64 个 descriptor word、数值文件、二进制和
总线条件相同，明确复用 36 条记录。因此实际运行数为 **84 条**，主表覆盖生产
默认设置的 **60 个配置**，不能解释为两套各 60 条均独立执行。

下表中的读取量只计原始输入有效字节，权重、bias 与量化参数另计。输出全部正确；
所选十层的有效输入需求覆盖各自完整输入，padding 外读均为零。

| 模型 / op | 输入 H×W×C → Cout | 核 / stride | 不同输入 B | 256 B 缓存总读 | 2 KiB 缓存总读 | 4 KiB 缓存总读 | 已测最小零重复缓存 |
|---|---|---|---:|---:|---:|---:|---:|
| MNIST / 0 | 28×28×1 → 8 | 3×3 / 1 | 784 | 784 | 784 | 784 | 256 B |
| MNIST / 2 | 14×14×8 → 16 | 3×3 / 1 | 1568 | 1568 | 1568 | 1568 | 256 B |
| Gesture / 1 | 64×64×1 → 8 | 3×3 / 2 | 4096 | 4096 | 4096 | 4096 | 256 B |
| Gesture / 7 | 16×16×16 → 32 | 3×3 / 2 | 4096 | 8224 | 4096 | 4096 | 2048 B |
| Gesture / 16 | 8×8×32 → 64 | 3×3 / 2 | 2048 | 3872 | 2048 | 2048 | 2048 B |
| Gesture / 10 | 8×8×64 → 32 | 1×1 / 1 | 4096 | 4096 | 4096 | 4096 | 256 B |
| Person / 6 | 24×24×32 → 32 | 1×1 / 1 | 18432 | 18432 | 18432 | 18432 | 256 B |
| Person / 10 | 12×12×64 → 64 | 1×1 / 1 | 9216 | 9216 | 9216 | 9216 | 256 B |
| MobileNetV2 / 32 | 14×14×192 → 64 | 1×1 / 1 | 37632 | 37632 | 37632 | 37632 | 256 B |
| MobileNetV2 / 52 | 14×14×96 → 576 | 1×1 / 1 | 18816 | 56448 | 55680 | 18816 | 4096 B |

“最小”仅指 256/512/1024/2048/4096 B 这五档中的已测值；它不是对未测容量的
理论下限。四个单输出通道组的 1×1 层在旁路下也没有重复输入字节；小缓存仍可能
通过较长 line 填充减少事务数量，所以同样字节数不代表同样周期。

MobileNetV2 op52 的自动设置是 R=2、W=16、3 个输出通道组。每个完整空间块
有 `2 * 16 = 32` 个位置，其原始输入工作集为 `32 * 96 = 3072 B`。2 KiB
容不下这批数据，处理后续输出通道组时需重读；4 KiB 可以保留它。实测如下：

| 模式 | 输入总读 | 重复读取 | 单字节最大读取次数 | cache miss | 命令周期 |
|---|---:|---:|---:|---:|---:|
| 2 KiB | 55680 B | 36864 B | 3 | 3480 | 377135 |
| 4 KiB | 18816 B | 0 B | 1 | 1176 | 353087 |
| 旁路 | 56448 B | 37632 B | 3 | 14112 | 397668 |

2 KiB → 4 KiB 的输入读取减少 **66.21%**，命令周期减少 **6.38%**；4 KiB
相对旁路的周期减少 **11.21%**。这些是固定 AXI 等待模型下的算子周期，不包含
软件配置或整个网络。显式 W=2 压力配置需要 18 个输出通道组，收益数字更大，
不能拿来代表默认驱动。Person op10 和 MobileNetV2 op32 默认 W=4、只有一个
输出通道组，五档缓存之间读取和周期完全相同。

因此，仅按 LRU 基线不能把 4 KiB 一概判为浪费，也不能用前两个小层的结果直接
将缓存设为 512 B。本文还比较了几何替换、选择性存入和索引优化下的 1 KiB 配置。
完整六模式流量、周期及逐字节 CSV 见
[复现入口](../test/conv_models/README.md)。

### 直接复用 IA 的设计评审

在原 IA RAM 增加少量 slot 元数据和一个仲裁读接口，可以根据窗口几何找到旧 tile
中的同一输入值，直接复制已校正的 s16，从而减少独立数据 RAM。按旧 tile 中相同
channel 的候选列反求输出位置，可避免逐元素 32 位地址 tag；后者在 SIZE=16、四个
slot 下仅地址就需 4 KiB，反而失去节省存储的意义。

该路径需要内容有效状态与原计算调度 valid 分开，读口优先满足原对角化输出。
当前填充 slot 可用 old/new 两个描述符与已提交前缀区分仍未覆盖的旧数据和已经
写好的新数据，不依赖器件的同址同拍读写行为。默认四个 slot 的完整描述符约
35 B，另有活动 slot / pending / 仲裁状态；这只是逻辑字段估算。

原调度还带来明确的驻留限制：SIZE=16、R=2、四个 slot、group_c=64 时，相同
channel 片段到下一 kernel tap 相隔四个 q 组，IA 只能容纳两个组。等真正需要
重叠数据时，旧内容已被覆盖；这种场景不能仅靠更聪明的查找解决。

真实 MobileNetV2 op52 还给出输出通道重放方向的容量例子：上述 3072 B 原始 s8
工作集写成 IA s16 后需要 6144 B，超过原 IA 的 2048 B。仅增加 IA 反查接口不能
让整个工作集驻留到下一输出通道组；若要取消独立输入缓存并保持该层每个输入
字节只读一次，还要改变调度或容量，并实测读口争用与总周期。功能上可以取消
缓存并接受重读；小工作集、低通道空间窗口仍有直接复用的价值。

详细公式、读口时序、old/new 前缀方案和限制见
[IA 直接复用设计评审](../test/conv_reuse/IA_REUSE_DESIGN_REVIEW.md)。
**当前生产 RTL 尚未实现 IA 读回查找 / 拷贝路径**；现有复用 PASS、周期与缓存容量
实验均属于原始输入地址缓存方案。该设计评审没有被混入已完成的 RTL 验证结果。

需要明确区分三种读流量：

| 情况 | 当前行为与保证 |
|---|---|
| 再次需要仍驻留的字 / line | 复用已有数据，不重新发外部 AXI 读取 |
| padding、归约尾部 | 本地产生零，不读取虚构的输入地址 |
| 输入分配首尾、4 KiB 边界 | 精确裁剪 / 分段；不允许读取输入 allocation 之外的字节 |
| line 内暂未使用的字节 | miss 默认填充整个有效 16 B line，可能预读 stride / dilation 跳过的位置或其他组通道 |
| 容量或 set 冲突导致逐出 | 以后再次访问需重新填充；不保证任意层中每个输入字节终身只读一次 |
| 新任务、同 batch 的另一个 group | 当前一致性合同要求重新失效；未实现跨任务输入 lifetime / generation 标记 |

因此，“重复窗口数据已复用”对应驻留数据不重复读的保证。对任意形状承诺“所有读取
字节都恰好是当前窗口所需且整层只读一次”超出了当前 line-cache 设计。特别稀疏的
访问可通过低层 `dsa_conv_s8_config_t.bypass_cache` 或 MMIO 做旁路对照；NMSIS
标准入口当前默认开启缓存，没有自动稀疏判定或公开的每层旁路参数。旁路仍按有效
32 位字取数，收益应使用实际轨迹衡量，不能由 kernel 大小单独推断。

逐地址复用核验由 [专用复用测试](../test/conv_reuse/README.md) 与原 NPU 的
[输入访问统计](../test/conv_npu/README.md) 提供，记录实际 AXI 接受的输入字节，
与权重、bias、量化参数读取分开。

SIZE=4/8/16 的逐地址计数均确认：上述 75 B 稠密输入的每个字节恰好读取一次，
重复读取为零；将 `Cout` 固定增加到 33、覆盖多个输出通道组后，仍保持这个结果。
所有 padding 对应的输入外读为零。旁路条件下，同样的多输出通道测试分别产生
3395 / 2340 / 1472 B 输入读取，说明减少的流量确实来自窗口与跨 tile 的复用。

同时，测试如实记录整行预取成本：矩形 stride / dilation 案例逻辑需要 200 个不同
字节，实际读取 272 个不同字节；分组案例需要 126 个，实际读取 336 个。两者的
单任务重复读取仍为零，但分别多取 72 B 和 210 B。详见
[复现入口](../test/conv_npu/README.md)。

计数依据 AXI `ARLEN/ARSIZE` 指定的有效 byte lane；它不等于 32 位 R 总线所有
数据线的传输位数，也不代表 DRAM 芯片内部取数粒度或能耗。

### LRU 基线：相同形状的缓存 / 旁路测量

输入均为 5×5×3，共 75 B；核 3×3，stride=1，padding=1。每一行的两种模式使用
相同数据、量化、总线等待和 tile 配置。`Cout=SIZE+1`，因此只能在同一行比较缓存
与旁路，不能将不同行当作同工作负载的阵列尺寸加速比。

| SIZE / Cout | 缓存输入读取 | 旁路输入读取 | 输入字节下降 | 缓存周期 | 旁路周期 | 周期下降 |
|---|---:|---:|---:|---:|---:|---:|
| 4 / 5 | 75 B | 679 B | 88.95% | 8480 | 9131 | 7.13% |
| 8 / 9 | 75 B | 780 B | 90.38% | 5126 | 5901 | 13.13% |
| 16 / 17 | 75 B | 736 B | 89.81% | 3976 | 4745 | 16.21% |

周期从 `calc_start` 接受到 `done_valid`，不包括 MMIO 配置，也不包括测试人为增加的
3 周期完成反压。输入流量下降与周期下降并不相等：窗口地址计算、初始化除法、
同步缓存访问、原阵列与输出写回仍消耗周期。`HITS/MISSES` 只统计进入地址缓存的
请求，不包含已被单字保持寄存器消除的请求；不能直接解释为卷积元素命中率。

## 历史执行范围与当前复现入口

下表首先保留硬件 Conv 集成 checkpoint 的分层结果。随后新增的几何策略最终源码
检查包括：13046 个预测器向量、39 个 cache 定向事务、6 个构建 / 25 条 NPU
命令、最终默认配置的真实 C/RTL 协同仿真，以及原 20 项 GEMM / WS / IS / PCR
的最终源码重跑。历史批次和新批次的来源分开列出，
未将修改前的测试重新标记为修改后执行。

| 层级 | 实际检查 | 结果及证据 |
|---|---|---|
| 独立数学参考 | 150 个形状，33366 个 INT32 输出，Python 与 GCC C 直接卷积 | PASS；[复现入口](../test/conv_frontend/README.md) |
| 前端 / adapter RTL | 8 配置 × 37 任务；SIZE 4/8/16，1/2 ways，8/16/32/256 B line；随机 AR/R/写端等待 | PASS；[复现入口](../test/conv_frontend/README.md) |
| 精确 span 读器 | 251 请求、913763 B、2043 bursts；非对齐、4 KiB、高地址、错误排空 | PASS；[复现入口](../test/conv_frontend/README.md) |
| 前端控制 | 23 个非法配置、描述符及恢复检查 | PASS；[复现入口](../test/conv_frontend/README.md) |
| 复用专项 RTL | cache 12 请求、真实 frontend 8 tile；冷填充、重复 / 重叠 tile 零外读、LRU 逐出、旁路单字保持、全 padding、任务失效 | PASS；[复现入口](../test/conv_reuse/README.md) |
| 共享读取保护器 | 10 逻辑请求、46 返回 word，2 个真实 RRESP 错误；4 GiB 进位和低地址别名检查 | PASS；[复现入口](../test/conv_guard/README.md) |
| 生产 SoC RAM | 6 组 × 270 命令，每组 3809 响应；outstanding 1/3/4，固定 / 随机等待 | PASS；[复现入口](../test/conv_soc_ram/README.md) |
| 原 NPU 完整 Conv 路径 | SIZE 4/8/16，共 54 任务；矩形 / stride / dilation / group、整内存核验、读错误恢复、Conv→IS GEMM→Conv | PASS；[复现入口](../test/conv_npu/README.md) |
| 原 NPU 逐输入字节核验 | 18 条额外命令；输入 / 权重流量分离，逐地址访问次数、未用预取、padding、多输出通道组 | PASS；[复现入口](../test/conv_npu/README.md) |
| 两套 C 驱动 / NMSIS 入口 | `-Wall -Wextra -Werror` + UBSan，9 个真实入口、batch/group、无能力 / busy / 错误 / timeout | PASS；[复现入口](../test/conv_driver/README.md) |
| 真实 C→AXI-Lite→NPU→生产 RAM | SIZE=4，固定 / 随机等待各 6 例；每组 1035 个硬件输出 + 100 个软件回退输出、10 条硬件命令 | PASS；[复现入口](../test/conv_cosim/README.md) |
| AXI-Lite 协议 | 6 组 / 103 项，WSTRB、busy 写 / 重复 START 拒绝、错误保持 / W1C / 恢复；2 有效任务 250 输出 + 1 无效任务 | PASS；[复现入口](../test/conv_cosim/README.md) |
| 裁剪配置能力 | `ENABLE_PER_CHANNEL=0`，15 项；驱动不 START；强制 Conv 返回 err=1，AR/AW/W VALID 全周期为零 | PASS；[复现入口](../test/conv_cosim/README.md) |
| 真实容量比较 | SIZE=16，256/512/1024/2048/4096 B 五档，各运行两个相同层 | PASS；[复现入口](../test/conv_npu/capacity.py) |
| 真实 CNN 模型尺寸 | 4 个模型提取 10 个原始普通 Conv 尺寸；5 档缓存 + 旁路；生产自动分块 60 配置，84 次实际运行含压力对照 | PASS；[复现入口](../test/conv_models/README.md)；24 条新增自动分块 + 36 条完全相同 descriptor 的实际记录复用 |
| 模型元数据 / 生产分块参考 | 全部 63 个普通 Conv，11986 通道量化参数、63 个激活范围和几何；实际 C planner 比较推荐 10 层 | PASS；[复现入口](../test/conv_models/verify_metadata.py)、[复现入口](../test/conv_models/driver_tiling_oracle.py)；不是新增 RTL 输出 |
| 旧 GEMM / WS / IS / PCR | 固定原 commit 与修改后各 20 例；输出、周期、AR 请求 / 字节、R 拍数、W 字节逐项比较 | 全部相同；[复现入口](../test/conv_regression/run.py) |
| 数据 RAM 逻辑推断 | 一个 1024×32 `$mem_v2`；1 同步读 + 1 同步写，4 个独立字节写使能 | PASS；[复现入口](../test/conv_ram_inference/README.md) |
| 几何预测器最终 RTL | 31 配置、13046 向量；未来事件、拒绝条件、done 时序 | PASS；[复现入口](../test/conv_replacement/predictor_test.py) |
| 选择性存入最终 RTL | 39 事务；未来替换、临时 line、延迟 hint、错误排空、范围和 LRU 回退 | PASS；[复现入口](../test/conv_replacement/run_cache_policy.py) |
| 专用替换最终 NPU | 6 构建 / 25 命令；10 层覆盖新默认 1 KiB，3 困难层多容量 / 策略对照 | PASS；[复现入口](../test/conv_replacement/README.md) |
| 专用替换后的 C/RTL | SIZE=4、新默认 1 KiB；固定 / 随机等待各 6 例，原 NMSIS、AXI-Lite、NPU 与生产 RAM；覆盖新默认容量与几何未启用路径，SIZE=16 几何快路由上述 25 条 NPU 命令覆盖 | PASS；[复现入口](../test/conv_cosim/README.md) |
| 最终源码原功能回归 | SIZE 4/8/16 共 18 例，加 PCR WS/IS 两例；原 20 项全部重跑，输出、周期及总线指标与最初基线相同 | PASS；[复现入口](../test/conv_regression/run.py) |

完整 C/RTL 协同仿真运行真实 NMSIS 与生产驱动。硬件调用期间宿主 CPU 的输入、
权重和输出页面设为 `PROT_NONE`，`ctx=NULL`；CPU 不能通过这些页面执行取窗、
卷积 MAC 或写出结果。测试用另一个 AXI master 在设备空闲时装载 / 读回生产 RAM，
然后逐元素核对输出和前后哨兵。每组的 100 个软件回退输出单独计数。

上述 C 程序由主机执行。目前未模拟 RISC-V 指令 / PicoRV32 固件启动，未运行
完整 TFLM 网络或板级测试。逻辑 RAM 推断也尚未扩展到完整 NPU 的工艺映射、
tag 面积、布局布线、最高频率和功耗评估。

### 发现并修复的主要问题

- IA 调度的 `tile_done` 与 ready 同周期，曾再次接收旧坐标 / slot；Conv 请求在完成
  脉冲期间保持 busy，避免重复发起并保留原 scheduler 推进顺序。
- 原 SoC RAM 忽略 narrow-read size，现已完成真实 RAM 模块测试及 C/RTL 接入。
- 原权重 DMA 的整字尾部读取会超出精确 allocation，新增保护器；接近 4 GiB 的
  地址递增保留 33 位进位，防止回绕到另一合法低地址区间。
- Conv 读取错误后先停止发新事务并排空总线，再复位内部任务状态；下一任务已核验
  正常执行。非法配置的新任务不会暴露上一个任务的缓存统计。
- 交付审查发现裁剪逐通道量化时仍公布 Conv 能力的问题，已使 `ENABLE_PER_CHANNEL=0`
  的能力查询返回零，并在核心拒绝强制 Conv；默认配置重跑结果保持一致，裁剪配置
  专项确认没有外存事务。
- 原交接包“读错误注入”向量落在全 padding tile，没有外部读而无法触发错误；
  修正为实际访问输入的窗口，当前生成器保留该错误注入条件。

新增前端的位宽、锁存、多驱动等诊断经过审查，没有通过删除断言制造 PASS。
完整 NPU 构建保留原模块警告；SIZE=4 C/RTL 构建共 9 条，来源为原 oa_writer、
vec_requant_s64、小字段比较、clock-gate latch 写法和 vec_s8_to_fifo 临时变量。
具体数量、审查结论和完整日志见 [C/RTL 说明](../test/conv_cosim/README.md)。

原 LRU 阶段的 capability 修复与后续默认 1 KiB / 几何策略实验分批执行；
表中的历史次数保留原范围，不将不同阶段计成同一批新运行。当前生产架构为
DMA 内统一 im2col，支持 WS/IS 的新执行范围见 [DMA 设计说明](block_dma_im2col.md)。
本次移除生成产物后的执行范围和生成方法单独见 [源码交付说明](conv_source_only.md)。

## 一键复现

在本仓库根目录、准备好 Python 3、GCC/G++、Verilator 和 Yosys 后执行：

```bash
make conv-verify VERILATOR=/absolute/path/to/verilator YOSYS=yosys
```

官方 Verilator 源码构建入口为
[`test/conv_regression/build_verilator.sh`](../test/conv_regression/build_verilator.sh)，
固定上述源码 commit 与依赖校验值。日志保留完整编译命令、工具版本和参与构建的
源文件摘要。默认构建目录是 `build/conv_verify`；可通过 `CONV_BUILD_DIR` 改到
空间充足的临时目录，`CONV_JOBS` 控制 NPU / C-RTL / GEMM 构建并行度。
独立前端、RAM、guard、复用和主机驱动测试使用各自 runner 的目录及并行设置。

只复核输入复用或集成路径时：

```bash
make conv-reuse VERILATOR=/absolute/path/to/verilator
make conv-input-audit VERILATOR=/absolute/path/to/verilator
make conv-capacity VERILATOR=/absolute/path/to/verilator
make conv-real-cnn VERILATOR=/absolute/path/to/verilator
make conv-replacement VERILATOR=/absolute/path/to/verilator
make conv-npu VERILATOR=/absolute/path/to/verilator CONV_SIZES='4 8 16'
make conv-cosim VERILATOR=/absolute/path/to/verilator
make conv-axil-protocol VERILATOR=/absolute/path/to/verilator
make conv-disabled-config VERILATOR=/absolute/path/to/verilator
make conv-gemm-regression VERILATOR=/absolute/path/to/verilator
make conv-ram-inference YOSYS=yowasp-yosys
```

标准集成使用 `CONV_CACHE_SETS=128`、`CONV_CACHE_POLICY=3`。测试脚本可显式选择
实验参数：`CONV_CACHE_SETS=32 CONV_CACHE_POLICY=2` 为 1 KiB 几何替换；
`CONV_CACHE_SETS=128 CONV_CACHE_POLICY=0` 为 4 KiB LRU。

不同测试的统计范围分别标出：模型输出、独立前端任务、整 NPU 任务、硬件命令
与软件回退输出不能相加当作同一类覆盖。测试执行时在 `build/` 或指定目录生成
数值向量、独立参考、日志、轨迹和构建报告，所有这些运行产物都不加入源码提交。
