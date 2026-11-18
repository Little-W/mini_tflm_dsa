# 卷积几何驱动的下一次 line 使用预测与选择性准入

## 实现范围

生产 block_dma 内的 im2col 前端与缓存实现以下替换和准入策略。WS 的 IA loader、IS 的 kernel loader 只请求普通矩阵块；DMA 返回矩阵元素。这里没有实现从 IA tile 直接复制旧元素，也没有建立整个 feature map 的逐字节地址表或 CPU im2col 计划。

标准集成的默认主数据容量现为 **1 KiB（32 sets×2 ways×16 B）**，默认 policy 2。512 B、2 KiB、4 KiB 均可通过原参数选择。默认缩小是存储与性能的明确取舍：例如 MobileNetV2 op52 的输入读取模型在 1 KiB、2 KiB、4 KiB 下分别为 43392 B、31104 B、18816 B；当前 DMA 架构的周期须由完整 RTL 运行测量，不沿用早期 IA 内前端的周期。主数据以外的 tag、next-use 和 transient 成本见后文。

`CONV_CACHE_POLICY` 从 `npu_axil_top`、`npu_top` 经过 `axi_block_dma_arbiter` 传入 `axi_dual_block_dma`，其内部前端和缓存对应参数为 `CACHE_POLICY`：

| 参数 | eligible job | 其他合法 job |
|---|---|---|
| 0 | 原始低位索引、LRU、正常准入 | 同左 |
| 1 | 几何 next-use、低位索引、选择性准入 | 原始 LRU |
| 2，默认 | 几何 next-use、可逆 XOR 索引、选择性准入 | 原始低位索引、LRU |

快路要求 SIZE=16、line=16 B、s8、输入基址和 group offset 对齐 16 B、Cin 和 group_c 为非零 16 的倍数、R 和 stride_h/w 为 2 的幂、kernel_h×kernel_w≤25，且整个任务的 line-event rank 空间小于 `0xffffffff`。dilation 使用配置乘法，不要求为 1 或 2 的幂。全局显式旁路不启用该策略。前端还要求原生 scheduler 的 tile p0/q0 对齐和有效 output-group context。

IS 调度与 WS 的 rank 顺序不同，当前通过 `cfg_sched_groups=0` 禁用几何策略，但原始输入 cache 在 job 内仍以 LRU 保留。未提供原生调度上下文的 standalone frontend 也默认 `cfg_sched_groups=0`。是否整输入已经可容纳而直接跳过预测，属于可选优化，本版未实现。

## 可预测的事件和 rank

上述条件下，一个输入 line 恰好是某个 pixel 的 16 个相邻通道。一行 A tile 使用完整的一个 line，形成四次 word 请求。预测的是这次整 line 使用结束后的下一次 line 事件，不把当前 line 内剩余三个 word 当成远期复用。

原生装载顺序为 `p-block → output-group → q-tile → R 个 p-tile → tile 内 row`。令 `Q=kernel_h*kernel_w*group_c/16`，为尾部 p-block 保留 rank 空洞，则：

```text
block_rows = R * 16
group_span = Q * block_rows
block_span = output_groups * group_span
rank = pblock*block_span + output_group*group_span
       + qtile*block_rows + (p % block_rows)
```

全任务只需同一组不可变配置。`ia_loader_ctrl` 在 `load_issue` 追加锁存 `tl_group`，预取时使用 `next_w_group_idx`，与该描述符的 p0/q0 同拍。没有根据回退的 q 地址猜测 output-group。

### 下一次使用的几何求解

`conv_next_use_predictor.sv` 对固定输入 `(iy,ix,channel_fragment)`，每周期扫描一个 kernel tap：

```text
ny = iy + pad_top  - ky*dilation_h
nx = ix + pad_left - kx*dilation_w
oy = ny / stride_h
ox = nx / stride_w
p  = oy*output_w + ox
q  = (ky*kernel_w+kx)*group_c + channel_fragment
```

先检查 ny/nx 非负、能被 stride 整除、oy/ox 在输出范围内。幂二 stride 的除法和余数分别用移位和 mask；p-block 和 q-tile 的分解也用移位。候选 p-block 早于当前块则丢弃；晚于当前块时取 output-group=0；同块中，若候选 `(qtile,p_local)` 晚于当前事件则使用当前 group，否则使用下一 group，超过 group 数则无效。取所有有效候选的最小 rank，没有未来使用时返回 `0xffffffff`。

这是针对 eligibility 条件的精确下一次 line 事件，而不是估计最近程度。预测器每周期接收一个 kernel tap，结果经过七级流水线，当前最多处理 25 个 tap。配置乘积逐级检查 32 位空间，保留 INF；运行时采用 64 位中间表达式防止截断混淆候选有效性。共享算术电路成本必须单列，不能把每周期一个 tap 等同于无成本预测。

## 与实际数据传输重叠

前端在 `ADDRESS` 阶段启动预测，比发出缓存请求提前两个阶段，结果由 `line_hint_valid/line_hint_rank` 保持。

- 首 word 命中：正常进入 RAM_READ，不等待扫描；若结果未到，缓存保存单个 pending `(set,way)`，结果到达时后台更新 next_use。
- 无效 way 的冷 miss：立即开始 AXI 填充，不等待扫描。只有填充已经结束而 hint 尚未完成时，COMMIT 等待结果。
- 满 set 的冲突 miss：确实需要比较三者的 next-use，才在 HINT_WAIT 等待 incoming hint。
- 同 line 后三个 word 不重新扫描、不改 next-use。next_use=INF 也不会立即失效该 line，以免当前 line 的剩余 word 重读。
- 下一事件启动必须等共享 predictor 空闲、缓存 pending hint 完成，防止旧 hint 被新事件覆盖。当前 line 的正常 word 命中不受 pending 阻塞。

`cfg_sched_r` 和 `cfg_sched_groups` 在配置握手时采样。预测器通过五个时钟阶段计算配置参数及其有效性，完成后将 `enabled` 传递给缓存；前端在配置完成前保持忙碌。

## 替换、准入和 transient 生命周期

每个主缓存 line 增加一个 32 位 `next_use`。命中返回本地数据；miss 优先选择无效 way。满 set 时，选择 next_use 最大的一路，相等取最低 way 编号。若 incoming 的下一次使用不早于该 victim，或者 incoming 已无后续使用，则不插入主缓存。这里比较的是将来使用，不使用历史 LRU 作为几何策略的替换依据。

不准入也必须满足当前需求。本版增加 **16 B transient buffer**，一次精确 line fill 后提供当前连续 line 的四个 word。接受任何不同 line 的请求时立即失效 transient，包含不同 line 的主缓存命中；它不会暗中成为跨 line 保留的额外全相联 way。

在填充前决定不准入时，严格不清 victim valid、不写主缓存数据、不修改其 tag/next_use。冷 miss 若 hint 尚未到，可先向无效 way 填充；如果结果后来是 INF，则不发布 tag，改由 transient 返回。这样的投机写只使用无效 way，不破坏驻留数据。不能直接切换旧的全任务 `cfg_bypass`：旧旁路用 way0 RAM 暂存 word，会覆盖已有驻留数据。新分支有独立 transient 数据和返回路径，全任务显式旁路仍保留原行为。`stat_hits` 包含 transient 命中，`stat_misses` 包含初次 transient 填充，实际字节仍按总线计数。

policy 2 的 set 为：

```text
raw_set = (addr >> LINE_BITS) & (SETS-1)
set = raw_set XOR ((addr >> (LINE_BITS+SET_BITS)) & (SETS-1))
tag = addr >> (LINE_BITS+SET_BITS)
```

tag 保持全部高位，给定 tag 和 hashed set 可以反求 raw set，不会因 XOR 丢失地址身份。整 job 的索引选择固定；fallback job 使用原低位索引。RAM 的 fill/read 都使用请求时锁存的 set。

## 数据正确性与协议合同

填充继续使用 `conv_axi_span_reader`，只读取 line 与分配区间的交集，保留首尾窄读、4 KiB 分段、RRESP/RLAST 校验与反压。实际字节计数仍来自有效 AXI 响应 lane。transient 只有在完整填充且无错误后才有效；错误返回前排空已接受的 span，失败的非准入请求不改变驻留数据。新配置清主 valid、transient 和 pending，input 内容变化不会沿用旧数据。

全 padding 不发输入请求，不启动预测。既有非法配置、越界请求和恢复机制继续工作。策略只改变读取与保留位置，不改变 s8 加 offset、IA s16 数据内容、阵列调度、权重或 requant 算法。

## 存储与控制成本

下表按 2 ways、16 B line 计算逻辑存储；transient 的 128 位数据、28 位 tag 和 1 位 valid 已计入并向上取整。不包含共享配置、pipeline 寄存器和组合算术，也不是 FPGA BRAM 宏面积。

| 主数据 | sets | 主 tag/valid/LRU | next_use 表 | transient 数据/tag/valid | 合计 |
|---:|---:|---:|---:|---:|---:|
| 512 B | 16 | 102 B | 128 B | 20 B | 762 B |
| 1024 B | 32 | 196 B | 256 B | 20 B | 1496 B |
| 2048 B | 64 | 376 B | 512 B | 20 B | 2956 B |

共享 predictor 顺序寄存器静态合计 581 位，此外还有前端 hint/上下文及 cache pending 寄存器。源码中宽乘法表达式不能直接等价为若干个 64×64 物理乘法器，也不能因配置只做一次就当作无面积。独立成本审查见 `cost/`；没有布局布线结果时，不宣称 Fmax、LUT 或宏面积已达标。

## 可再生验证与边界

- 独立 predictor：31 配置、13046 向量通过，其中 13027 个 next-rank 与 forward 事件序列/几何 oracle 完全相同，19 个拒绝配置返回 INF；1…25 tap 延迟、done 和结果保持均检查。
- 独立 cache：39 事务通过，覆盖非 LRU victim、选择性准入、transient 生命周期、三种 delayed hint、RRESP 排空恢复、配置失效、首尾/4 KiB、非法地址、LRU 回退与全局旁路。
- 完整 NPU：`make conv-replacement` 现生成数值与自动 tiling，执行六个 profile、25 个任务。标量 C 卷积/NMSIS requant 核对完整输出，forward 模型逐字节核对真实 AXI 输入次数。没有历史报告或向量作为必需输入。下表是该调度/准入模型的读取预期，可由 `focus.py` 现算；实际执行结果写到本次 build 目录。

| 主缓存 | policy | Gesture7 输入 B | Gesture16 输入 B | MobileNetV2 op52 输入 B |
|---:|---:|---:|---:|---:|
| 512 B | 2 | 6176 | 2688 | 49536 |
| 1 KiB | 0 | 8208 | 3872 | 55680 |
| 1 KiB | 1 | 5840 | 2784 | 43392 |
| 1 KiB | 2 | 4976 | 2400 | 43392 |
| 2 KiB | 2 | 4096 | 2048 | 31104 |
| 4 KiB | 2 | 4096 | 2048 | 18816 |

读取量与周期是不同指标：XOR 和 next-use 不保证每例更快，几何计算与仲裁也有控制延迟。MobileNetV2 op52 的 2 KiB 数据容量仍小于一个满 p-block 的 3072 B 工作集，在原调度顺序下不能达到 4 KiB 的全层只读一次。完整调用的吞吐与 CPU 开销应使用当前 DMA / SoC runner 测量，不能把减少重读写成消除了全部重读。

本实现之外的通用精确 next-use、按剩余次数替换、IA slot 直接复制、更多预取或循环重排均没有在本版声称完成。
