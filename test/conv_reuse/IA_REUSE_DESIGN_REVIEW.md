# 用 IA tile RAM 复用卷积输入：只读设计评审

**状态：方案评审，尚未实现。** 本文只读审查现有调度和 RAM；`run.py` 检查现有 raw cache/word buffer，其生成结果不代表本文提出的 IA 读回机制已经通过仿真。

## 1. 当前数据布局和推进次序

`rtl/npu/loaders/ia_loader_ctrl.sv` 在 `load_issue` 锁存 `tl_p0`、`tl_q0`、slot 和有效行数。每次 `tl_tile_done` 将 p 游标增加 SIZE、写 slot 指针增加 1。装载和发送的逻辑次序为：

```text
for p_block in output-position blocks of R*SIZE:
  for output-channel group:
    for q0 in reduction tiles, step SIZE:
      load R IA tiles: p0=p_block, p_block+SIZE, ...
      send these R tiles for each of W output-channel tiles
```

下一 q 组可以在当前组第一次 W 发送时开始预取；下一组究竟是 q 增加、输出列组重启 q=0，还是 p 行块前进，由 `next_l1_idx`、`next_w_group_idx` 和 `next_group_advances_l2` 决定。它并非按输入像素行保留一整行的滑窗 line buffer。

`rtl/npu/loaders/ia_loader_cache_mgr.sv` 的 bank 是 A 矩阵列 `col`，bank 内地址是 `{slot,row}`。一个 slot 保存 `A[p0+r,q0+b]`，数据已加入 input offset，宽度为 s16。当前 RAM 读回只连接阵列发送路径，没有连接 im2col 前端。

因此当前已经由 IA tile 保留消除的是 **同一个 A tile 发送给 W 个输出列 tile 时的重复装载**。不同窗口在 A 中可能出现相同输入值的多个 s16 副本，但前端生成这些副本时仍访问 word buffer/raw cache；当前没有从先写入的 IA 元素复制到后续元素的机制。

## 2. 从当前输入坐标反查旧 slot

同一任务内，给定当前目标输入坐标 `(iy,ix,ch)`，其中 ch 是 group 内通道，旧 slot 元数据为 `p0_old,q0_old,rows_old`。全局配置保存 output_w、kernel_w、group_c、stride、dilation、padding 和 input offset。新任务接受时清除全部 resident 标记即可；如果要跨任务保留，则必须另加完整任务身份和配置一致性检查。

最适合现有列 bank 的反查方式是枚举旧 slot 内相同通道的列 b：

```text
q_old  = q0_old + b
ch_old = q_old % group_c
tap    = q_old / group_c
ky_old = tap / kernel_w
kx_old = tap % kernel_w

ny = iy + pad_top  - ky_old*dilation_h
nx = ix + pad_left - kx_old*dilation_w
```

只有 `ch_old == ch`、`q_old < reduction_len`、ny/nx 非负且分别能被 stride_h/stride_w 整除时继续：

```text
oy_old = ny / stride_h
ox_old = nx / stride_w
p_old  = oy_old*output_w + ox_old
r_old  = p_old - p0_old
```

检查 oy/ox 在输出范围、`0 <= r_old < rows_old`，再检查该元素仍保存旧内容，即可得到源 bank=b、源地址=`slot*SIZE+r_old`。匹配一个有效输入坐标已排除 padding；归约尾部仍必须显式排除。输入 s16、input offset、group offset 等必须属于同一任务，复制值无需再次加 offset。

不用遍历所有列：若 slot 保存 `q0_old % group_c`，第一个候选为 `b0=(ch-(q0_old%group_c)+group_c)%group_c`，之后每次 b 增加 group_c。当 group_c>=SIZE 时每 slot 至多一个候选；stride=1 时反查不需要除法。通用 stride 的整除判断可以复用顺序除法器，但不能将候选扫描和多个 32 周期除法称为免费命中。另一种方式是扫描旧行并除 dilation 反求旧 kernel 坐标；适合 dilation=1 的路径，可与列扫描择优。

最小实现可先覆盖 stride=1 的列扫描，其他几何回退现有外部读取；要覆盖全部合法几何则需要顺序搜索状态机或更多算术硬件。已有前端只在 tile 初始化时除 p0/q0，逐元素增加通道和 kernel 坐标；新增搜索不能把通用组合除法放回关键路径。

## 3. 一个可实现的最小读回接口

在 `ia_loader_cache_mgr` 增加单笔 `reuse_req(slot,row,bank)` / `reuse_rsp(s16)` 接口，每个 bank 的原生 diagonal 读拥有优先权：

- `rd_en_pipe[bank]==0` 时，借用该 bank 的物理读口；如果该拍原生读恰好读取同一地址，也可以直接捕获原生读的返回值。
- 原生读访问其他地址时等待，不暂停、不重排对角 token。
- 同步 RAM 返回延迟需要单独的借读 owner 标记和 bank 选择寄存器，返回数据放进一个可反压的保持寄存器。
- **必须分离物理读使能与原生 diagonal 使能。** 现有 `ram_rd_en_d1` 直接控制 `ia_out` 和 `ia_row_valid`；如果将借读使能直接 OR 进去，会产生伪阵列输入。阵列 valid、tile_done 和 l1_done 必须继续只由原生 token 驱动。
- 同地址读写不能依赖 FPGA RAM 的未约定 read-during-write 行为，应拒绝冲突拍或使用已提交的前端值旁路。

`ISSUE_GAP_CYCLES=0`，组内 tile 连续发送。如果一组有 T 个有效行，bank j 连续忙 T 周期，相对 bank 0 延迟 j 周期；完整组的对角读窗口长 T+SIZE-1。在这段窗口内每 bank 总共只有 SIZE-1 个首尾空闲周期，组间空闲另外计算。例如 SIZE=16、R=2、满 tile 时每 bank 连续占用 32 周期，47 周期窗口里该 bank 空闲 15 周期；中间 17 周期所有 bank 同时忙。不同 bank 的空闲时间不同，不能假设 compute 期间始终可以读任意源元素。

前端可以先用已有 word buffer 命中，然后查询 IA，IA 未命中再访问外部。最小 IA 返回一次只提供一个 corrected s16，直接进入写出路径，令该次 send_count=1，不再次加 input offset；之后可扩成两个 bank 的并行复制。等待 IA 读口不会破坏当前 compute 的输出，但可能延迟下一组预取，最终增加组间等待。

## 4. resident 内容、覆盖和 source pin

现有 `blk_valid` 表示供计算调度使用的 tile；最后一次 W 发送的 `cache_tile_done` 会将其清除。物理 RAM 并未清零，所以另设 `resident_valid` 可以在 retire 后保留旧内容，直到开始覆盖或新任务失效。

最保守版本只允许读取非当前目标 slot 的完整 resident tile。当前 Conv 一次只装载一个 tile，`tl_busy` 阻止下一次 load；因此其他 slot 在本次 fill 期间没有另一写者。无需将所有候选 slot 长期 pin 住，只需保证借读返回已捕获后才结束当前 fill，下一次 load_issue 不与未完成借读冲突。若显式增加 source_pin，它只需覆盖 RAM 读被接受到数据进入返回寄存器这段时间，并参与相同 slot 的 load/write 仲裁。长时间 pin 住待写目标 slot、同时等待当前 fill 完成，会造成自锁，应避免。

可以在新 `load_issue` 到第一次实际写入之间继续保留目标 slot 的旧 descriptor；新 descriptor 暂存在 pending 寄存器。第一拍写入时将整个旧 resident 标记失效，提交完成后再令新 descriptor 有效。这是容易验证的版本，但当前 tile 内的重叠、以及覆盖过程中的旧 tail 都无法利用。

更有价值且仍无需每元素 valid 的版本使用现有前端的严格行优先写入顺序：

- 为当前写 slot 保留旧 descriptor 和新 descriptor，并记录一个 `committed_prefix`，单位为已经完成写入的 A 元素。
- 线性索引 `< committed_prefix` 的位置属于新 tile，可用于同一个 A tile 内已经生成部分的复用。
- 索引 `>= committed_prefix` 的位置若在旧 rows 范围内，仍属于旧 tile，可作为旧内容来源。
- prefix 只在实际写握手完成后前进；两条候选映射分别检查所属范围。新 tile 完成后丢弃旧 descriptor。

这依赖前端现在的连续 wr_mask 和行优先顺序，不能直接推广到任意 DMA 稀疏写。读取旧 tail 的结果进入寄存器后，可以安全覆盖相应地址。被提前覆盖的旧数据无法恢复；prefix 只保证不会误把新数据当旧数据，并不保证所有潜在重用都命中。

## 5. 哪些窗口数据还在

同一输出行中，相邻输出位置要复用同一输入，旧 kernel x 必须比新 kernel x 大 `stride_w/dilation_w`，且这个值为整数。stride=dilation=1 时，旧 reduction 列比新列大 group_c。若两列落在同一个 q tile，已经完成的上一行就能提供当前行的数据。例：SIZE=4、group_c=1 的 3×3 卷积，旧行的 kernel-x=1 元素可以复制给新行的 kernel-x=0 元素；需要上述新 tile prefix 机制才能利用首个正在生成的 tile。

如果 group_c>=SIZE，一个 q tile 通常只涵盖一个 kernel tap 的全部或部分通道；同一 tile 的相邻 p 行在这个 tap 上访问不同输入，没有这种列间复用。空间重叠要等同一通道 slice 的另一个 kernel tap 出现。

以 SIZE=16、R=2、4 slots、group_c=64 为例，q 装载组依次是：

| q 组 | kernel tap | 通道 |
|---|---|---|
| 0 | 第一个 tap | 0..15 |
| 1 | 第一个 tap | 16..31 |
| 2 | 第一个 tap | 32..47 |
| 3 | 第一个 tap | 48..63 |
| 4 | 下一个 tap | 0..15 |

装第 4 组时，四个 slots 只能保存最近两组的内容，第 0 组已经被覆盖，故所需同通道的重叠输入不在 IA 中。单纯加元数据和读回端口无法消除这种重读。group_c=16 时相邻 tap 只隔一组，上一组数据通常仍在；group_c=32 时隔两组，源恰好可能位于待覆盖的目标 slot，此时保留旧 tail 比首写整 slot 失效更有价值。输出行换行、dilation 和 p 行块边界还会改变所需旧 p 位置，必须用坐标映射判定，不能只认“上一个 slot”。

## 6. 元数据成本与实施选择

在 SIZE=16、4 slots 时，每 slot 保存 p0 32 位、q0 32 位、rows 5 位、resident_valid 1 位，合计 280 位，即 **35 B** 新元数据。任务配置统一失效时不必每 slot 再存 task ID。当前写 tile 的 prefix 为 9 位；还需要少量 pending descriptor、请求/返回状态和端口 mux。为降低反查开销而预存解码坐标会增加寄存器；35 B 不是整个新增逻辑的面积。

若改为给每个 IA 元素附加完整 32 位原始输入地址和 1 位有效位，仅 tag/valid 就需要：

| SIZE，4 slots | IA 元素数 | 每元素 33 位元数据 |
|---|---:|---:|
| 4 | 64 | 264 B |
| 8 | 256 | 1056 B |
| 16 | 1024 | 4224 B |

还不包括查找比较器与选择网络。按元素加地址 tag 容易吞掉原本想节省的容量；descriptor 加坐标推导更紧凑，但有查找周期和算术逻辑代价。

若目标是实际去掉专用 4 KiB RAM，应新增编译期结构选项，令 IA 未命中回退到已有精确边界的 word/span 读取，或选用一个很小的 raw cache。仅将运行时 `bypass_cache` 置 1 并不等同于从结构上删除现有 RAM。能否接受该选择，需要比较外部字节和总周期：小通道空间卷积可能适合 IA prefix/相邻组复制；大通道、需要隔多组才能再访问相同通道的卷积仍会丢失相当多复用机会。本文未修改生产 RTL，也没有为尚未实现的方案声明速度或节省量。

## 7. 仓库真实 CNN 层的几何条件

以下来自 [`extract_shapes.py`](../conv_models/extract_shapes.py) 从仓库模型即时生成的清单，使用 SIZE=16、4 slots、目标 R=2，并按小形状和最后一个 p 块修正有效 R。`analyze_ia_geometry.py` 对全部 63 个 regular INT8 Conv2D 层生成 `build/conv_reuse/real_layer_ia_geometry.json`；这里列出实际容量实验选择的 10 层。**这是调度和几何条件分析，不是 IA 读回复用的 RTL 命中率。** 该机制仍未实现。

Q 是一整个 p 块的 reduction tile 数；H/V 是同一 p 块内、单独沿水平/垂直方向产生相同输入所需的最小 kernel 位移对应的 q tile 距离。最小 kernel 位移为 `stride/gcd(stride,dilation)`，对应输出位移为 `dilation/gcd(stride,dilation)`；1×1 没有这种空间窗口重叠。源 tile 的装载年龄为 `gap*R_eff+i_current-i_source`；4 slots 下年龄小于 4 才仍在其他 slot，等于 4 落入待覆盖目标 slot，需要 old-tail，超过 4 已被覆盖。gap=0 则还要检查当前 tile 的已写 prefix。

| 模型/op | 输入 → 输出，省略 batch | kernel/stride | R，末块 R | Q | H / V 的 q 距离 | 直接 IA 复用条件 |
|---|---|---|---|---:|---|---|
| mnist/0 | 28²×1 → 28²×8 | 3×3 / 1 | 2，1 | 1 | 0 / 0 | 当前 prefix 及相邻 p 块有机会 |
| mnist/2 | 14²×8 → 14²×16 | 3×3 / 1 | 2，1 | 5 | 0–1 / 1–2 | 水平 prefix/旧组；满块最远垂直源可涉及 old-tail |
| justure/1 | 64²×1 → 32²×8 | 3×3 / 2 | 2，2 | 1 | 0 / 0 | 同 q tile；需要已写 prefix 或旧 p 块 |
| justure/7 | 16²×16 → 8²×32 | 3×3 / 2 | 2，2 | 9 | 2 / 6 | 水平源可在 old-tail；同 p 块垂直源已覆盖 |
| justure/16 | 8²×32 → 4²×64 | 3×3 / 2 | **1，1** | 18 | 4 / 12 | 全层仅 1 个 p tile；水平源是 old-tail，垂直源已覆盖 |
| justure/10 | 8²×64 → 8²×32 | 1×1 / 1 | 2，2 | 4 | 无 / 无 | 不存在空间窗口重叠 |
| person/6 | 24²×32 → 24²×32 | 1×1 / 1 | 2，2 | 2 | 无 / 无 | 不存在空间窗口重叠 |
| person/10 | 12²×64 → 12²×64 | 1×1 / 1 | 2，1 | 4 | 无 / 无 | 生产自动 W4 仅一组；强制 W2 才有两组 |
| mobilenet_v2/32 | 14²×192 → 14²×64 | 1×1 / 1 | 2，1 | 12 | 无 / 无 | 生产自动 W4 仅一组；强制 W2 才有两组 |
| mobilenet_v2/52 | 14²×96 → 14²×576 | 1×1 / 1 | 2，1 | 6 | 无 / 无 | 生产自动 W16 有三组；强制 W2 为十八组 |

这些条件仍受输入边界、实际旧 p 范围、覆盖 prefix 和 bank 空闲时刻约束；跨 p 块时，旧块最后几个 kernel taps 也可能匹配新块边界窗口，不能由固定 p 块内的 q 距离推导整层命中率。尤其 justure/16 的输出只有 16 个位置，实测软件 tiler 选择 R=1；若机械套用满 R=2 会把水平源误判为已被覆盖。

显式 requested R=2/W=2 与生产 requested R=0/W=0 是不同规划策略。压力配置下 person/10、mobilenet_v2/32 各两组，mobilenet_v2/52 十八组；这些数字不能代表驱动默认行为。运行 [`driver_tiling_oracle.py`](../conv_models/driver_tiling_oracle.py) 可从当前 C header 即时核对生产自动策略。SIZE16/IA4/PS16 普通配置下，前三层分别选择 W4、W4、W16，即一组、一组、三组；justure/16 为 R1/W4，仅一组。分析脚本可对显式提供的当前 RTL 报告逐字段核对，但默认不读取历史结果或声称重新执行过整层 RTL。

这些 1×1 层的满 p 块原始输入分别为 `32*64=2048 B`、`32*192=6144 B`、`32*96=3072 B`。前两层默认只有一个输出列组，不能用组间重播论证大缓存优势；6 KiB 的整个 p 块工作量也不表示单次流式读取必须有 6 KiB 缓存。mobilenet_v2/52 默认仍有三组，3072 B 原始块存在组间重播，而 IA 4 slots 只能保留最后两个 q 组。任何容量的实际流量和周期收益应由当前 RTL 的新执行报告给出。

本次模型清单中的 C64 及以上代表层主要是 1×1；前面的 C64/3×3 是结构性反例，不能当作这些模型中真实存在的某层，更不能当作已经执行过的 IA-only 对照。
