# NMSIS 驱动与真实 SoC 的 im2col 性能对照

当前补丁固定以上游 `148964d180f52cb852c5a7e3d5c89773fa0a8ea5` 为基线。
仓库仅保存测试源码与本报告；模型层信息、输入、权重、量化参数、golden、
固件和运行日志均在测试时生成。生成方法与本次复验范围见
[源码交付说明](conv_source_only.md) 和
[`test/conv_soc_perf`](../test/conv_soc_perf/README.md)。

## 1. 比较对象

本实验比较在同一 SoC、同一 NPU 上执行普通 s8 卷积的两种实现：

| 路径 | CPU 工作 | NPU 工作 | 外部 im2col scratch |
|---|---|---|---|
| 原软件 im2col + DSA GEMM | 原 `riscv_conv_acc.c` 以 32 行为一批展开 s8 输入并发出 GEMM 命令；1×1 直接读取原图矩阵 | 既有 GEMM 阵列与量化 | 通用空间卷积需 32 × aligned(Q,4) B；原 1×1 不需要 |
| DMA 硬件 im2col | 当前 NMSIS 校验参数、提交原始 NHWC / OHWI 地址并等待 | block_dma 生成输入矩阵，随后使用同一阵列、部分和与量化 | 硬件路径不使用，测试传入 NULL scratch |

原软件基线精确取自仓库提交
`e8a73373009064026fd0be1cbf3af6870d592ebb` 的
`drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/riscv_conv_acc.c`。
测试只对公开符号作私有重命名以便与新路径链接在同一个固件中；保留原循环、
32 行分批和原 1×1 wrapper 的逐输出行命令行为。原矩阵加速 helper 仍连接相同
DSA GEMM 驱动和 RTL。源码快照、SHA 与重命名方法随测试交付。

这不是“纯 CPU 卷积与全硬件卷积”的对比。当前代码将 `DSA_NN_CONV_ENABLE=0`
时使用的普通 NMSIS 软件 kernel，也不是本实验的历史加速基线。保持 GEMM 阵列
相同，才能观察移除 CPU 窗口展开、外部展开矩阵搬运和多次命令提交后的整体变化。

## 2. 真实 SoC 执行路径

仿真实例化生产 `soc_top`：PicoRV32 CPU、native-to-AXI bridge、SoC 互连、
AXI-Lite NPU 控制、NPU、时序缓冲及生产 `soc_axi_ram`。CPU 从 RAM 中的 RV32
固件取指，通过真实 MMIO 访问 NPU；测试台不替 CPU 写 NPU 寄存器。

PicoRV32 使用仓库固定的 submodule commit
`ef203c2b0a3fb793280f5114941416c425c5b461`。CPU 开启 M 扩展乘除与 32 位 cycle
计数器，主比较关闭 instruction cache，与本仓库 SoC 默认值一致。NPU 采用
SIZE16、IA 四个 slot、16 个 PS frame、标准 s16 内部激活、s8 权重和逐通道量化，
原图主 cache 为默认 1 KiB / 策略 2。最终编译参数、RAM 容量、交叉编译器版本和
每次仿真的等待条件以 build manifest 为准。

两条主路径链接在同一 ELF 中，由测量开始之前的描述符选择；相同层使用相同代码
布局、输入、权重、bias、量化、输出和 scratch 地址。每个模式独立冷启动，避免
先执行的模式为后执行模式预热 CPU / NPU 状态。初始化和完整输出校验位于计时区间外。

这与 `test/conv_cosim` 不同：后者由主机编译的 C 驱动发出真实 AXI-Lite 请求，
适合验证调用和硬件数值；本实验的 C 指令由 SoC 内 PicoRV32 执行，才可比较 CPU
im2col 和驱动准备开销。主机 wall-clock 时间不用于性能结论。

## 3. NMSIS 驱动更新

所有受支持 s8 入口共用 `riscv_convolve_s8_try_dsa`，在 CPU im2col 之前尝试
硬件路径。新增 `DSA_NN_CONV_DATAFLOW_MODE` 编译选项：0 为 WS 默认值，1 为 IS，
其他取值在编译时报错。选项写入低层 `dsa_conv_s8_config_t.dataflow_mode`，并在
START 前检查所需的 Conv / narrow read / IS 能力位；缺少能力时保留合法回退。

模式不会改变公共 NHWC / OHWI / NHWC 布局。WS 时 IA loader 请求 im2col；IS 时
kernel loader 请求 im2col；完整图像几何和原图 cache 均由共享 DMA 管理。
主性能对比使用默认 WS，另以编译选项 1 的实际 SoC 固件验证 NMSIS IS 入口。
该附加执行不混入主 WS 加速比。

## 4. 测量定义与公平条件

主要指标是完整 NMSIS 调用首尾的真实 CPU `rdcycle` 差值：

\[
T_{call}=cycle_{after\ return}-cycle_{before\ call}
\]

这个区间包含真实 CPU 参数校验、窗口展开（原路径）、驱动分块规划、MMIO 配置、
等待和状态处理。主计时没有给每个 DSA 调用插入 `--wrap` 探针，也不以手工估算
的每元素开销替代 CPU 执行。32 位计数器使用模减，仿真上限和外部 cycle 计数
约束保证没有跨越整个计数周期而丢失信息。

测试台还累计真实 NPU 工作区间和总线握手，因此可报告：

\[
T_{outside\ NPU}=T_{call}-\sum T_{NPU\ active}
\]

它表示非 NPU 执行区间，包含 CPU 准备、提交、状态处理和相关等待，**不能直接
命名为纯 im2col 耗时**。CPU 在 NPU 工作时的轮询与硬件执行可能重叠，也不能
把这两个量按“CPU 指令成本”重复相加。

CPU instruction / data 流量、NPU 读取与写入按实际握手统计；原始输入、权重、
量化参数和软件 scratch 根据真实地址区间分类。性能标记包围完整调用，比 CSR
首尾略宽；若流量采用此标记窗口，结果中单独说明。`CONV_CYCLES` 只适用于
Conv 任务；固件对 legacy GEMM 将该字段标为 `UINT32_MAX`（不适用），它的
NPU 周期由测试台的真实 busy 区间统计。

硬件模式同时要求真实 `HW_CONV` START，原路径要求 GEMM START；命令类型、
次数和矩阵请求 owner 都核对。这样不能由软件 fallback 恰好算对输出来冒充
硬件加速成功。每个输出元素由固件和测试台分别与独立 golden 比较，并检查输出
前后保护字节。输入初始化、golden 生成、输出比较和打印不计入 `T_call`。

加速比与总周期减少分别为：

\[
Speedup=\frac{T_{software\ im2col+GEMM}}{T_{hardware\ im2col}},\qquad
Reduction=1-\frac{T_{hardware\ im2col}}{T_{software\ im2col+GEMM}}
\]

加速比小于 1 就表示变慢，不能只保留正向样本。

## 5. 真实 CNN 尺寸

选自已有 TFLite 模型的完整层尺寸：

| 层 | 输入 H×W×C | 核 / stride | 输出 H×W×C | 作用 |
|---|---|---|---|---|
| MNIST op0 | 28×28×1 | 3×3 / 1 | 28×28×8 | 小通道、padding、许多 CPU 展开块 |
| MNIST op2 | 14×14×8 | 3×3 / 1 | 14×14×16 | 多通道 3×3 |
| Gesture op7 | 16×16×16 | 3×3 / 2 | 8×8×32 | 几何替换适用、输入重叠 |
| Gesture op16 | 8×8×32 | 3×3 / 2 | 4×4×64 | 较长归约、单个原 32 行批次的尾块 |
| MobileNetV2 op52 | 14×14×96 | 1×1 / 1 | 14×14×576 | 不需要滑窗复制的控制项、大输出通道数 |

模型来源、文件 SHA 与算子元数据来自 [`test/conv_models`](../test/conv_models/README.md)。
使用固定种子的合成输入、权重、bias、逐通道量化与完整独立 golden，保留原始
尺寸。输入 offset 为 −7，输出 offset 为 −3，activation 范围为 [−117, 109]；
这些是测试参数，不是各 TFLite 层原有的量化配置。不声称执行了训练权重的完整
CNN，也不将算子加速比直接当作整网加速比。

MobileNetV2 的 1×1 原入口直接使用原图矩阵，没有通用 3×3 的 CPU 展开循环。
其变化包括命令粒度、驱动准备、数据格式与 DMA 调度，不可把全部差值归因于移除
软件 im2col。四个 3×3 样本也会同时受到命令合并和外部 scratch 搬运减少的影响；
本报告给出完整调用收益，而不是声称已将这些原因完全拆成独立比例。

## 6. 结果与复现

### 6.1 完整 NMSIS 调用

主比较使用 GCC 14.2.0、`-O3`、RV32IM、相同的官方 newlib RISC-V 内存例程，
CPU instruction cache 关闭，RAM 的额外固定响应等待为 0。等待为 0 并不表示
总线零周期：生产 bridge、仲裁、时序缓冲和 RAM 握手仍然运行。两种模式使用同一
ELF / SoC executable，每次从独立冷复位启动。

| 层 | 原 CPU im2col + GEMM 周期 | DMA 硬件 im2col 周期 | 加速比 | 总周期变化 | 原 / 新 START 数 |
|---|---:|---:|---:|---:|---:|
| MNIST op0，3×3 | 3101984 | 90726 | 34.19× | 减少 97.08% | 25 / 1 |
| MNIST op2，3×3 | 918635 | 76012 | 12.09× | 减少 91.73% | 7 / 1 |
| Gesture op7，3×3 | 320174 | 61739 | 5.19× | 减少 80.72% | 2 / 1 |
| Gesture op16，3×3 | 114883 | 58183 | 1.97× | 减少 49.35% | 1 / 1 |
| MobileNetV2 op52，1×1 | 397961 | 600717 | **0.6625×** | **增加 50.95%** | 14 / 1 |

四个 3×3 层的完整调用都加速，1×1 控制项出现退化。当前 NMSIS dispatcher
根据支持能力和参数合法性选择硬件，不包含按上述实测性能自动绕过 1×1 的策略，
因此不能据此宣称“全部受支持卷积均更快”。原 1×1 路径本来没有 CPU im2col，
这里保留负结果作为路径选择的依据。

这 10 次主测每次都成功返回；两种模式各核对 125376 个输出字节，合计 250752
个。每次的完整输出分别由 CPU 和测试台检查，二者并不重复计作新增输出数量。
所有保护字节、实际 START 类型、START / DONE 次数和 im2col 请求 owner 检查通过；
硬件模式的外部 im2col scratch 指针为 NULL，没有软件回退后误报硬件成功。

### 6.2 收益来自哪里

| 层 | 原 / 新 NPU busy 周期 | 原 / 新非 NPU busy 区间 |
|---|---:|---:|
| MNIST op0 | 10534 / 73314 | 3091450 / 17412 |
| MNIST op2 | 8457 / 56616 | 910178 / 19396 |
| Gesture op7 | 6140 / 38188 | 314034 / 23551 |
| Gesture op16 | 7268 / 26537 | 107615 / 31646 |
| MobileNetV2 op52 | 289954 / 441841 | 108007 / 158876 |

当前硬件展开前端加入了窗口寻址、原图 cache 和矩阵流生成；对照的原 GEMM
直接消费已展开矩阵，NPU 内部工作较少。本次五个样本的新 NPU busy 周期都高于
旧路径。3×3 的端到端收益来自大幅减少 CPU 展开、分批规划 / 提交及相关开销，
不能描述成阵列 MAC 或 NPU 本体变快，也不能将非 NPU 区间全部当作纯 im2col。

CPU instruction read 次数在前四层分别从 327147、93004、30382、9885 次下降
为 1430、1638、2077、2930 次。1×1 则从 10085 次上升为 16274 次，新驱动
还实际读取了 6912 B bias / multiplier / shift 数据用于参数数值范围检查。
这些观测支持上述方向判断，但没有把每条指令或每类检查单独归因到周期。

### 6.3 实际总线流量与 scratch

本表单位均为 B。“CPU 输入读”是 native bus 接受的 32 位读传输字节，不能
直接等同于 C 层访问的 s8 元素数；scratch 写按有效写 lane 统计。它们均取自
BEGIN / END 标记窗口，该窗口在主测中比 CSR 周期区间多 45 个周期。

| 层 | 原 CPU 输入读 | 原 scratch 写 / NPU 读 | 新 CPU 输入读 | 新 NPU 原图读 | 新 scratch 写 / 读 |
|---|---:|---:|---:|---:|---:|
| MNIST op0 | 26896 | 7056 / 9408 | 0 | 784 | 0 / 0 |
| MNIST op2 | 12800 | 14112 / 14112 | 0 | 1568 | 0 / 0 |
| Gesture op7 | 8464 | 9216 / 9216 | 0 | 4976 | 0 / 0 |
| Gesture op16 | 3872 | 4608 / 4608 | 0 | 2400 | 0 / 0 |
| MobileNetV2 op52 | 0 | 0 / 0 | 0 | 43392 | 0 / 0 |

MNIST op0 的原 GEMM 输入 stride 对 Q=9 作了对齐，因此 scratch 的实际 NPU
读取量与 CPU 写入量不同；不把对齐读掩盖成完全相等。1×1 原图直接由 NPU 读
56448 B，CPU 无需展开。五个硬件样本的 CPU 原图读及外部 scratch 搬运都为 0。

包括权重和量化参数在内的 NPU 读取总量为：

| 层 | 原 NPU 读取字节 | 新 NPU 读取字节 |
|---|---:|---:|
| MNIST op0 | 14808 | 5316 |
| MNIST op2 | 23520 | 10592 |
| Gesture op7 | 19200 | 14960 |
| Gesture op16 | 23808 | 21600 |
| MobileNetV2 op52 | 927360 | 478848 |

1×1 的总读下降 448512 B，其中原图少 13056 B，权重少 387072 B，量化参数少
48384 B。大部分来自命令 / 分块粒度改变后权重和参数加载减半，而不是原图 cache
独自带来的收益。即使读流量显著降低，NPU busy 和 CPU 侧区间仍一起增加，最终
完整调用慢了 50.95%。

### 6.4 IS 入口与 RAM 等待补测

使用 `DSA_NN_CONV_DATAFLOW_MODE=1` 重新编译真实 NMSIS 固件，MNIST op0
在 IS 模式消耗 **88933** 个完整调用周期，NPU busy 为 70852 周期。实际观察到
1 次 IS Conv START、49 个 kernel im2col 分块、0 个 IA im2col 分块，6272 个
输出字节及保护区全部正确。这证明编译选项实际到达新硬件接口；单个样本不支持
将 IS 普遍性能或 WS 几何替换优势外推到所有层。

Gesture op7 另以相同 ELF、冷复位、`RAM_FIXED_LAT=4` 成对执行：

| 额外固定 RAM 等待 | 原完整调用周期 | 硬件 WS 完整调用周期 | 加速比 | 总周期减少 |
|---|---:|---:|---:|---:|
| 0 | 320174 | 61739 | 5.19× | 80.72% |
| 4 | 496114 | 75876 | 6.54× | 84.71% |

等待为 4 时两条路径完整输出、START 类型 / 数量及分块 owner 仍全部通过。CPU
instruction read 次数及各数据流量与等待为 0 时相同，增加的是实际等待周期；
标记窗口此时比 CSR 区间宽 65 周期。这个定向检查表明该样本的改善并不依赖
零额外等待条件，不代表已经完成全部模型和存储配置的延迟扫描。

主比较 10 次、等待补测 2 次、IS 1 次，共 **13 次真实 CPU 性能运行**，涉及
58 次 NPU 命令（51 次原 GEMM、7 次硬件 Conv），261120 个输出字节全部匹配。
独立 CPU 寄存器 smoke 测试不计入该性能数量。

### 6.5 证据与重新执行

每次执行都会在输出目录写入结果、每层周期与流量、逐输出比较、固件 / 编译源
摘要以及精确运行命令，入口见
[`test/conv_soc_perf`](../test/conv_soc_perf/README.md)。除主比较外，还执行
编译期 IS 选择和额外 RAM 等待条件的定向对照；这些结果单独列出，不混入上述
五层 WS 表。运行生成的逐次执行数据与 CSV 优先于摘要中的四舍五入值。
这些文件保留在用户选择的输出目录，不随补丁提交。

具备仓库固定 PicoRV32 submodule、Verilator 和包含 newlib 的裸机 RISC-V
工具链后，主对照入口为：

```bash
make conv-soc-perf VERILATOR=/path/to/verilator \
  CONV_RISCV_GCC=/path/to/riscv64-unknown-elf-gcc
```

本次本地分离安装的 GCC / newlib 使用方法、官方内存例程的重建命令，以及 IS /
额外延迟的精确参数均在测试 README 中给出。测试台不使用主机函数代替 CPU，
也没有使用旧 NPU-only 仿真的周期替代这里的 SoC 测量。

## 7. 结论的适用边界

结果对应清楚列出的 PicoRV32、编译器优化、memory latency、CPU instruction cache
和 NPU 配置。更换 CPU、加入数据 cache、不同外存等待或改变软件批量，会改变
CPU 展开与硬件工作的比例。这里报告 cycle 与实际总线字节，不推测 Fmax、功耗
或换算未经时序收敛的真实时间。

本实验固定使用标准核心 `PCR_ENGINE=0`。最新上游共享配置文件默认启用 PCR，
该核心不提供硬件 Conv 能力；普通构建与本实验的固定配置需要明确区分。更新后的
两份 C 驱动保留上游 PCR planner 和其合法性检查，未绕过上游容量约束。

默认 1 KiB 几何 cache 的读取优化，以及统一 block owner 相对旧 IA-local 前端
减少的并行机会，已在 [DMA 设计说明](block_dma_im2col.md) 分别量化。SoC 性能
对照是在统一后的同一硬件上进行；既保留其真实成本，也计入 CPU 展开被移除的收益。
