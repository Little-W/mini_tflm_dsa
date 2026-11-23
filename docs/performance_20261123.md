# NPU 性能优化与公开加速器比较

日期：2026 年 11 月 23 日。

远端仓库为 [Little-W/mini_tflm_dsa](https://github.com/Little-W/mini_tflm_dsa)，起始提交为 `e6caf608e3aeca205b956908a38b4d229209529c`。本次生产 RTL 与调度器对应提交 `8cbd624115243a6cefe5d71c9d3808463c7ce693`，生产文件摘要见 [measured_sources.json](data/performance_20261123/measured_sources.json)。

## 1. 结果

31 种共同 GEMM 形状逐项领先 Gemmini-BiRD、Apache VTA 和 Google Coral NPU VME。开启 `CONV_LOW_LATENCY=1` 后，另外 3 项普通卷积与 2 项深度卷积也逐项领先 Gemmini-BiRD。独立 NVDLA 比较中的 3 项 GEMM 均领先 NVDLA。

单位为周期，合计表示每个算例执行一次的周期总和。

| 运算 | 数量 | 远端 NPU | 优化后 NPU，低延迟 | Gemmini-BiRD | VTA | Coral VME |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GEMM | 31 | 180,852 | **149,991** | 219,155 | 380,112 | 1,141,561 |
| 普通卷积 | 3 | 154,993 | **86,138** | 150,563 | 未测量 | 未测量 |
| 深度卷积 | 2 | 136,764 | **36,525** | 50,517 | 未测量 | 未测量 |
| 全部共同算子 | 36 | 472,609 | **272,654** | 420,235 | 未测量 | 未测量 |

GEMM 总周期相对远端减少 17.06%，相对 Gemmini 减少 31.56%，相应加速比为 1.461×。36 项总周期相对远端减少 42.31%，相对 Gemmini 的加速比为 1.541×。

### 重点 GEMM 形状

`M×N×K` 表示 `A[M,K] × B[K,N]`。

| M×N×K | 远端 NPU | 优化后 NPU | 最快的公开比较对象 | 对方周期 | 周期差 |
| --- | ---: | ---: | --- | ---: | ---: |
| 1024×16×144 | 30,427 | **20,787** | Gemmini-BiRD | 29,731 | 8,944 |
| 64×64×576 | 13,742 | **12,752** | Gemmini-BiRD | 12,834 | 82 |
| 9×256×256 | 13,667 | **8,747** | VTA | 12,495 | 3,748 |

`64×64×576` 由生产调度器自动选择 WS、R4、W4。调度计算使用通用传输与计算代价，生产代码未增加针对上述形状的分支。

## 2. 设计

### GEMM 调度

`drivers/dsa_memory_schedule.h` 根据输入流时间，估计权重预取中可与当前输入流执行重叠的传输时间。后续权重安装与当前输入流执行重叠，调度器据此评价数据流与复用参数。空间卷积继续使用其对应的代价计算。

### 部分和帧调度

`ps_frame_store.sv` 在当前输出末尾写入期间接收下一条请求，并允许最后一次 RAM 写入、当前帧完成和下一帧准备在同一个周期发生。下一帧的初始读取可以提前开始。

同步 RAM 读取使用 `replay_launch_q` 保证数据有效时间；单行同址读写由 `prepare_read_conflict` 延后读取。取消尚未接受的请求时，已经开始执行的命令继续完成。该修改新增两个状态位，保持处理单元数量与数据存储容量不变。

### 量化参数组启动

`vec_requant.sv` 分别计算当前输出行的参数有效状态与下一组的启动许可。逐通道模式在当前参数组末行到达时，保留该行的数值运算，下一参数组等待参数装载完成。IS 模式跨列复用同一参数组时继续允许启动；整张量模式的启动条件保持连续有效。该处理使用现有的分块状态与组合逻辑。

### 深度卷积输入复用

`vector_engine_address.sv` 在最后一个通道组被处理单元接受时释放输入位置，使后续窗口请求能够提前使用该位置。处理单元在释放边沿取得当前操作数，后续窗口经过描述符队列，在之后的边沿写入。

### 深度卷积结果转发

`vector_engine.sv` 在最后一组 MAC 结果返回时构造完整快照。当前返回组从 `pe_result` 取得数值，其余组从 `acc_buf` 取得数值；输出快照与下一像素偏置初始化可以在同周期进行。共享与私有存储路径均使用这一处理方式。

### 卷积前端与配置

卷积描述符完成与下一项提交重叠，在共享存储端口允许时，一次写入多个输入元素。`CONV_LOW_LATENCY` 从配置、顶层 RTL、仿真、综合及容量统计入口传递到卷积前端。设为 `1` 时使用直接描述符与缓存响应配置；默认值为 `0`。

## 3. 实验条件

NPU 使用 16×16 矩阵阵列、16 个向量处理单元、9×4096 字节共享存储、16 KiB 图像缓存、AXI64、最多 4 个读事务与 4 个写事务在途，以及 `raw32` 部分和存储。

共同数值任务为 INT8 输入与权重、INT32 累加及偏置，输出为 `clip_INT8(RNE((A×B+bias)/32))`，零点为 0。主比较包含数据读取、计算、INT8 输出写入及全部外存响应结束；主机布局转换与调度计算不计入单算子周期。外存容量为 2 MiB，接受 AR 后最早 8 周期返回首拍，连续服务为每个方向每周期 1 拍，NPU 的最大突发为 2048 字节，各实现遵守 4 KiB 地址边界。Coral 的实际传输均为 16 字节单拍。

| 实现 | 固定源码版本 | 接口 | 逻辑状态容量 |
| --- | --- | --- | ---: |
| NPU，低延迟 | 本文生产源码 | AXI64 | 653,349 bit，81,668.625 B |
| NPU，默认配置 | 本文生产源码 | AXI64 | 653,666 bit，81,708.25 B |
| Gemmini-BiRD | 硬件 `4a33b75f975297e309847f41f81f4c0f8b20b81d`；软件 `576f08c217dfefb9fa2e3e087575f23699565560` | AXI64 | 650,391 bit |
| VTA | `d4a15f627d5cc9762a82270d1be60a136e6af9c2` | AXI64 | 627,138 bit |
| Coral NPU VME | `f385a31b4af454be21063fca1d17351b35a3a99c` | 原生 AXI128 | 665,344 bit，完整核心 |

Google 于 2026 年 10 月 20 日公开了包含 Matrix Execution Unit 的完整 Coral NPU 32 位架构。本次选取表列固定提交的源码版本，作为近期公开实现的比较对象，参见 [Google 官方发布说明](https://developers.googleblog.com/unifying-edge-ai-how-coral-npus-open-standard-brings-portable-energy-viable-intelligence-from-model-to-silicon/)。

Gemmini 使用包含深度卷积扩展的 BiRD 版本，其 GEMM 调度从 456 个候选中选择并独立重放；计时从首条配置 RoCC 指令开始，到 FENCE 完成及外存响应结束，命令通过独立 RoCC 接口发送。VTA 计入指令和 micro-op 传输。Coral 使用所列固定版本的完整 `VmeCoreMiniAxi`，计入外存至 DTCM 的复制、标量控制、矩阵计算与 RVV 后处理；程序与控制数据预先存放于 TCM，该列对应本次通用程序的实际结果。各实现的容量范围与接口条件按表列出。

两种 NPU 配置均完成实际 RTL 展开及能力参数核对。低延迟配置距 80 KiB 限制尚有 251.375 字节余量，默认配置尚有 211.75 字节余量。[容量结果](data/performance_20261123/capacity.json)保存了配置、状态构成与源码摘要。性能数据来自逐周期 RTL 仿真；第 8 节给出标准单元映射与模块静态时序估计。

## 4. GEMM 逐项结果

两种 NPU 配置的 31 项 GEMM 周期相同。

| M×N×K | 远端 NPU | 优化后 NPU | Gemmini-BiRD | VTA | Coral VME |
| --- | ---: | ---: | ---: | ---: | ---: |
| 16×16×16 | 211 | 210 | 345 | 483 | 706 |
| 32×32×32 | 562 | 552 | 789 | 1,537 | 3,033 |
| 64×64×64 | 2,222 | 2,128 | 2,914 | 5,898 | 17,023 |
| 17×23×19 | 444 | 432 | 1,722 | 952 | 1,931 |
| 1×64×64 | 643 | 643 | 853 | 768 | 4,279 |
| 784×8×9 | 2,263 | 2,262 | 5,704 | 13,847 | 20,317 |
| 196×16×72 | 4,048 | 2,746 | 7,936 | 5,582 | 14,067 |
| 1×64×784 | 6,493 | 6,493 | 7,822 | 6,919 | 46,759 |
| 1×10×64 | 207 | 192 | 409 | 318 | 1,168 |
| 2304×8×27 | 15,223 | 9,808 | 16,204 | 41,936 | 83,817 |
| 2304×16×8 | 8,632 | 8,631 | 11,845 | 39,344 | 55,069 |
| 576×32×16 | 4,000 | 3,990 | 6,619 | 19,961 | 33,901 |
| 576×32×32 | 4,564 | 4,504 | 7,352 | 21,305 | 46,281 |
| 144×64×32 | 2,346 | 2,268 | 4,147 | 11,046 | 23,743 |
| 144×64×64 | 3,964 | 3,702 | 5,252 | 12,449 | 36,543 |
| 36×128×64 | 2,860 | 2,670 | 3,545 | 7,150 | 24,435 |
| 36×128×128 | 4,783 | 4,369 | 5,960 | 9,447 | 42,867 |
| 9×256×128 | 7,251 | 4,507 | 8,045 | 8,005 | 34,419 |
| 9×256×256 | 13,667 | 8,747 | 17,436 | 12,495 | 65,139 |
| 1×2×256 | 507 | 432 | 1,285 | 725 | 3,997 |
| 125×64×40 | 3,984 | 3,101 | 6,187 | 10,156 | 23,867 |
| 125×64×64 | 3,635 | 3,445 | 4,633 | 10,848 | 32,447 |
| 1×12×64 | 218 | 208 | 410 | 318 | 1,168 |
| 1024×16×27 | 7,579 | 5,107 | 8,767 | 19,134 | 38,569 |
| 1024×16×144 | 30,427 | 20,787 | 29,731 | 31,817 | 117,664 |
| 256×32×144 | 8,703 | 8,530 | 8,799 | 14,531 | 59,901 |
| 256×32×288 | 16,659 | 16,288 | 19,162 | 22,079 | 110,121 |
| 256×32×16 | 2,251 | 2,247 | 2,951 | 9,034 | 15,261 |
| 64×64×288 | 7,262 | 6,776 | 7,455 | 12,170 | 59,023 |
| 64×64×576 | 13,742 | 12,752 | 12,834 | 24,721 | 113,023 |
| 64×64×32 | 1,502 | 1,464 | 2,042 | 5,137 | 11,023 |

## 5. 卷积逐项结果

形状按输入高宽、输入通道和输出通道标注，卷积核均为 3×3。`S1`、`S2` 分别表示步幅 1、2。

| 运算 | 远端 NPU | 优化后 NPU，默认 | 优化后 NPU，低延迟 | Gemmini-BiRD |
| --- | ---: | ---: | ---: | ---: |
| Conv 96×96，C3→8，S2 | 82,162 | 82,158 | **52,860** | 85,503 |
| DW 48×48，C8，S1 | 107,012 | 88,275 | **25,614** | 32,710 |
| DW 48×48，C8，S2 | 29,752 | 23,890 | **10,911** | 17,807 |
| Conv 32×32，C16→16，S1 | 55,118 | 45,775 | **19,805** | 24,562 |
| Conv 8×8，C64→64，S1 | 17,713 | 17,781 | **13,473** | 40,498 |

默认配置的 36 项总周期为 407,870。默认配置下 `Conv 8×8，C64→64` 比远端增加 68 周期，读取与写入流量保持相同；部分和提前准备改变了输入与权重请求的到达时刻。低延迟配置的 5 项空间算子均减少周期，其中两项深度卷积相对远端分别减少 76.06% 和 63.33%。

## 6. NVDLA 独立比较

此组采用独立的整数输入变换与读地址间隔条件：`A′=2A`、`W′=16W`、`bias′=32bias`，结果精确除以 32，读地址接受间隔至少 2 周期。NVDLA 固定提交为 `1a65f1f5b48268accaa47c95f95c2601918be095`，使用 `nv_small_256`、C32/K8、AXI64 和 128 KiB CBUF。此处 128 KiB 仅计 CBUF 容量。实际 43,328 个输出值按共同逻辑顺序逐字节比较一致。

| 算例 | 优化后 NPU，低延迟 | NVDLA 引擎 | NVDLA 包含配置 |
| --- | ---: | ---: | ---: |
| GEMM 16×16×16 | 210 | 576 | 831 |
| GEMM 64×64×64 | 2,128 | 7,075 | 7,330 |
| GEMM 1×64×64 | 643 | 1,324 | 1,579 |
| Conv 96×96，C3→8，S2 | 52,860 | 41,807 | 42,062 |
| Conv 32×32，C16→16，S1 | 19,805 | 23,960 | 24,215 |
| Conv 8×8，C64→64，S1 | 13,473 | 12,937 | 13,192 |
| 合计 | 89,119 | 87,679 | 89,209 |

NPU 在 3 项 GEMM 与 `Conv 32×32` 中周期较少，NVDLA 在另外 2 项卷积中周期较少。NVDLA 引擎计时从首次引擎使能开始；包含配置的计时从第一条 CSB 写入开始。逐项输出摘要与输入一致性检查见 [nvdla_ar2.json](data/performance_20261123/nvdla_ar2.json)。

## 7. 验证

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| 共同算子 | 两种配置各 36 项，完整预期外存图像、实际输出、计时与全部响应结束时刻 | 通过 |
| 补充数值测试 | 两种配置各 20 项 GEMM、6 项空间算子，覆盖非整块尺寸、连续 K 分组和通道余数 | 通过 |
| 部分和记录 | 16 帧、774 行、12,384 个 INT32 值，10 次同周期完成与接收，3 类无效事件检查 | 通过 |
| 部分和存储 | 465 个命令、156,656 个 INT32 读回值、24,576 项地址检查 | 通过 |
| 向量执行单元 | 私有 PE8、共享低延迟 PE8、共享默认 PE16；每种 616 项、170,743 个输出值 | 通过 |
| GEMM 调度 | 800 个随机共享配置、71 项几何检查、10 项自动选择检查 | 通过 |
| 存储策略 | 4 个软件配置，每个 1,534 项检查和 54 次启动 | 通过 |
| 调度缓存 | 2 个配置，每个 51 个独立计划 | 通过 |
| AXI 调度 | 42 项传输、18 项无效配置、60 项量化分组检查 | 通过 |
| 量化数值与组交接 | 两种计算配置，共 6,000,800 个 INT8/INT16 元素；并行附加 320 个配置、1,168 次参数组切换 | 通过 |
| 完整逻辑状态容量 | 两种配置，实际展开并核对能力参数 | 通过 |

算子复核确认了每种配置的 155 个编译输入文件摘要。补充空间算子中的窄读请求按实际有效字节与物理拍容量检查。结果见 [低延迟验证](data/performance_20261123/verification_fast.json)、[默认配置验证](data/performance_20261123/verification_registered.json)和[部件测试](data/performance_20261123/component_tests.json)。

### 完整模型

四个模型分别使用两个固定输入样本运行 `perf` 和 `trace`。以下数值为两个 `perf` 样本的完整 `MicroInterpreter::Invoke` 周期算术平均值。远端参考提交为 `e6caf608`，当前两种配置采用同一生产源码 `8cbd6241`，并分别设置 `CONV_LOW_LATENCY=0` 和 `CONV_LOW_LATENCY=1`。完整运行记录、原始文件 SHA-256、硬件参数与源码摘要见 [models.json](data/performance_20261123/models.json)，平均周期见 [models.csv](data/performance_20261123/models.csv)。

| 模型 | 远端参考 | 当前默认配置 | 当前低延迟配置 |
|---|---:|---:|---:|
| MNIST CNN | 74,825.5 | 73,870.5 | 61,267.5 |
| MobileNet V1 VWW | 663,453.5 | 600,678.5 | 359,705.5 |
| ResNet8 CIFAR-10 | 893,156.5 | 867,509.5 | 778,404.5 |
| DS-CNN KWS | 226,651.5 | 211,405.5 | 116,341.5 |

每种配置的八次 `perf` 运行合计分别为 **3,716,174、3,506,928、2,631,438 周期**。当前默认配置相对远端参考减少 **5.63%**，周期比为 **1.0597×**；当前低延迟配置减少 **29.19%**，周期比为 **1.4122×**。周期比按远端总周期除以当前总周期计算。

#### 初始化与规划计时

固件通过 CPU `rdcycle` 读取完整 `MicroInterpreter::Invoke` 的起止周期。该区间包含解释器的算子调度与执行；初始化和调用结束后的输出检查分别位于区间之外。`trace` 运行逐个记录算子输出，用于数值检查，其附加记录时间不参与上表平均值。计时实现位于 [`test/model_benchmark/firmware.cc`](../test/model_benchmark/firmware.cc)。

`init_cycles` 从 `InitializeTarget` 之前开始，包含模型读取、算子注册、解释器构造、`AllocateTensors`、输入复制和张量信息记录。`planning_cycles` 累加 [`dsa_schedule_cached_plan`](../drivers/dsa_schedule_impl.h) 的测量时间，包括计划缓存查询和计划生成；该数值在调用 `Invoke` 之前读取，**已经包含在初始化周期中**。每次运行均从重新启动的模拟系统开始。当前两种配置的初始化和规划数值相同：

| 模型 | 初始化周期 | 其中规划周期 | 实际 tensor arena 使用量，字节 |
|---|---:|---:|---:|
| MNIST CNN | 11,093,910 | 6,158,575 | 66,324 |
| MobileNet V1 VWW | 74,671,144 | 20,040,623 | 314,596 |
| ResNet8 CIFAR-10 | 42,106,191 | 31,241,708 | 138,644 |
| DS-CNN KWS | 17,638,158 | 6,270,188 | 49,172 |

当前初始化范围为 **11,093,910 至 74,671,144 周期**，其中规划范围为 **6,158,575 至 31,241,708 周期**。计算首次运行的初始化与推理总周期时，应将 `init_cycles` 与 `invoke_cycles` 相加；规划周期已计入初始化。tensor arena 配置容量为 524,288 字节，外部系统 RAM 为 2,097,152 字节；这些数值与 NPU 内部 80 KiB 状态容量分别记录。

#### 输出与源码审计

两种当前配置共完成 **32 次运行**，包含 16 次 `perf` 与 16 次 `trace`。结果记录中的 **1,792 项检查全部通过**。`trace` 共记录 **272 个张量**，其中 256 个为中间张量，16 个为最终输出，合计 1,726,736 字节；每个张量均与准备目录中的整数参考结果逐字节一致。所有运行的最终输出及预测类别均通过检查，模型和输入内容在执行后保持一致。具体检查名称、每个张量的字节数和 SHA-256 均保存在 `models.json`。

独立字节比较分别读取远端与当前默认配置、远端与当前低延迟配置的实际文件。每组比较包含 16 个最终输出文件、16 个模型文件、16 个输入文件和 136 个记录张量文件，共 **184 个文件、3,168,888 字节**，全部一致。两组合计 **368 次文件比较、6,337,776 字节**。

源码检查重新计算了两种配置模拟器的 170 个仓库源文件及固件的 401 个仓库源文件摘要，并核查各自外部依赖。模拟器、性能固件与张量记录固件的构建记录均声明构建期间源码未发生变化；两种当前配置记录的源码摘要均与当前文件一致。审计工具摘要如下：

| 工具 | SHA-256 |
|---|---|
| `audit_model_outputs.py` | `f2455e8980233b0c49f876775922475f22651b8844f63e6a030136528a3ef1b2` |
| `compare_model_bytes.py` | `67067177a50b20bfe428610bf42909005a95a6d6c781d8780077d4d28997885c` |
| `run_storage_models.py` | `2ea51d07a2a3591a02ef8e61612d5cad25f923afebc6dff39d771a43f63c35f8` |

#### 独立复核命令

从仓库根目录执行以下命令。目录变量指向本次保存的模型运行结果和参考张量；移动实验目录后，可调整这些变量。三个审计命令分别检查远端参考、当前默认配置与当前低延迟配置；两个比较命令再次读取实际文件并比较全部字节。审计工具使用常规 Python 模式，开启断言检查。

```sh
MODEL_REFERENCE_RESULTS="/absolute/path/to/reference_model_results"
MODEL_DEFAULT_RESULTS="build/performance_20261123/models_registered/results"
MODEL_LOW_LATENCY_RESULTS="build/performance_20261123/models_fast/results"
MODEL_PREPARED="/absolute/path/to/npu_gemmini_bird_axi64_80k_20261117/prepared"
MODEL_AUDIT_OUT="build/performance_20261123/model_audit"

python3 test/gemmini_comparison/audit_model_outputs.py \
  --results-root "$MODEL_REFERENCE_RESULTS" \
  --prepared-root "$MODEL_PREPARED" \
  --out "$MODEL_AUDIT_OUT/reference.json"

python3 test/gemmini_comparison/audit_model_outputs.py \
  --results-root "$MODEL_DEFAULT_RESULTS" \
  --prepared-root "$MODEL_PREPARED" \
  --experiment-runner test/gemmini_comparison/run_storage_models.py \
  --out "$MODEL_AUDIT_OUT/registered.json"

python3 test/gemmini_comparison/audit_model_outputs.py \
  --results-root "$MODEL_LOW_LATENCY_RESULTS" \
  --prepared-root "$MODEL_PREPARED" \
  --experiment-runner test/gemmini_comparison/run_storage_models.py \
  --out "$MODEL_AUDIT_OUT/fast.json"

python3 test/gemmini_comparison/compare_model_bytes.py \
  --reference "$MODEL_AUDIT_OUT/reference.json" \
  --current "$MODEL_AUDIT_OUT/registered.json" \
  --reference-results-root "$MODEL_REFERENCE_RESULTS" \
  --current-results-root "$MODEL_DEFAULT_RESULTS" \
  --out "$MODEL_AUDIT_OUT/bytes_reference_to_registered.json"

python3 test/gemmini_comparison/compare_model_bytes.py \
  --reference "$MODEL_AUDIT_OUT/reference.json" \
  --current "$MODEL_AUDIT_OUT/fast.json" \
  --reference-results-root "$MODEL_REFERENCE_RESULTS" \
  --current-results-root "$MODEL_LOW_LATENCY_RESULTS" \
  --out "$MODEL_AUDIT_OUT/bytes_reference_to_fast.json"
```

## 8. 综合与时序估计

使用 Yosys 0.71+40（`pyosys==0.71.post40`）、ABC 和 OpenSTA 2.0.17，分别对远端与当前版本的七种模块配置进行完整标准单元映射及静态时序分析。工艺参考为 Nangate45 Open Cell Library 的 typical 条件，电压 1.1 V、温度 25°C。该库用于研究和 EDA 流程评估，参见 [库说明](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/82ac25be57125cc724388ef89f01ce65f9ba3dcc/flow/platforms/nangate45/README.md)。库文件 SHA256 为 `8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1`。

时钟频率设为 150 MHz，周期为 6.666667 ns。建立时间不确定度为 0.666667 ns，保持时间不确定度为 0.125 ns；最大输入、输出延迟各为 1.333333 ns，最小延迟为 0 ns；输入和时钟转换时间为 0.1 ns，每个输出端口位负载为 5 fF。采用库内 `5K_hvratio_1_1` 统计线负载模型与理想时钟。ABC 使用 `BUF_X1` 输入驱动、5 fF 输出负载和 6000 ps 目标。

每个模块的两版实现采用相同的映射流程和约束。并行量化器使用显式 `map` 序列，其余六种配置使用默认 ABC 序列；完整命令和源码摘要保存在 [timing.json](data/performance_20261123/timing.json)。每个模块内部的存储、寄存器和组合逻辑均映射到标准单元，外部共享存储和服务通过原有 RTL 端口表示。两版共有十四项映射结果，覆盖寄存器间、输入至寄存器、寄存器至输出以及输入至输出路径。

两版完整量化器均通过 ABC CEC 组合等价检查；映射前后的 54 个端口、3,667 个端口位和 18,091 个顺序单元的名称及类型逐项保持。最终时序分析使用这些通过等价检查的网表。

综合流程按实际转换时间与负载选择更高驱动能力的标准单元。每次选择均比较 Liberty 的引脚功能和顺序逻辑定义，保持所有连接及顺序单元数量，并重新执行建立时间、保持时间和转换时间检查。调整后的十四项模块结果均满足建立时间与转换时间约束。

下表中的寄存器间到达时间对应最差建立时间路径，包含寄存器的时钟到输出延迟；最小建立、保持余量分别取四类路径中的最小值。面积变化采用完成驱动选择后的库单元面积。

| 模块 | 远端寄存器间到达时间 / ns | 当前寄存器间到达时间 / ns | 当前最小建立余量 / ns | 当前最小保持余量 / ns | 库单元面积变化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 部分和存储 | 1.753 | 2.131 | 2.824 | -0.107 | +0.011% |
| 向量执行 | 2.742 | 2.752 | 2.228 | -0.186 | +0.517% |
| 卷积描述符，低延迟 | 1.295 | 1.301 | 1.499 | -0.125 | +0.046% |
| 卷积描述符，默认 | 1.132 | 1.177 | 1.280 | -0.119 | +0.110% |
| 卷积数据流，低延迟 | 1.928 | 1.863 | 1.626 | -0.125 | -0.042% |
| 卷积数据流，默认 | 2.029 | 1.900 | 1.532 | -0.125 | +0.047% |
| 完整并行量化器 | 1.812 | 1.812 | 2.857 | -0.098 | +0.000179% |

新的 `o_group_ready` 输出路径建立时间余量为 **2.857053 ns**，扣除最大输入延迟后的模块内组合延迟为 **0.476281 ns**。部分和提前准备增加了部分地址控制的组合延迟；当前寄存器间路径到达时间为 2.130556 ns，对应建立余量为 3.835629 ns。向量最后一组 MAC 结果直接参与输出快照，当前相关寄存器至输出路径到达时间为 2.438421 ns，建立余量为 2.228245 ns。

保持时间按同一组最小延迟与不确定度计算，当前最小余量为 **-0.186259 ns**。本次完成的是模块综合后估计，未进行时钟树构建、布局布线或 SRAM 宏时序分析；保持时间和芯片最高频率需要在实际工艺与物理实现条件下继续计算。所有动态端点均有时序约束，常量和未启用功能的输出另行分类。

[timing.csv](data/performance_20261123/timing.csv) 保存完整数值，[timing_paths.csv](data/performance_20261123/timing_paths.csv) 保存逐类路径结果，`data/performance_20261123/timing_reports/` 保存完整路径报告、SDC 与转换时间检查。

## 9. 复现

需要用户提供的 `npu_gemmini_bird_axi64_80k_20261117` 参考环境，其中包含固定工具链、准备后的模型、共同输入及外存模型。以下命令从导入后的仓库根目录运行，`TASK_REF` 指向解压目录；`TASK_OUT` 指向输出目录。

```bash
TASK_REPO="$PWD"
TASK_REF="/absolute/path/to/npu_gemmini_bird_axi64_80k_20261117"
TASK_OUT="$TASK_REPO/build/performance_20261123"
TASK_PY="$TASK_REF/tools/python/bin/python3"
TASK_VERILATOR="$TASK_REF/tools/verilator/bin/verilator"
export VERILATOR_ROOT="$TASK_REF/tools/verilator"
export PYTHONPATH="$TASK_REPO/test:$TASK_REPO"

"$TASK_PY" test/capacity/check_elaboration.py \
  --target generic --bus-width 64 --vector-pe-count 16 \
  --verilator "$TASK_VERILATOR" --output-root "$TASK_OUT/capacity_fast" \
  --set PCR_ENGINE=1 --set SIZE=16 --set IA_CACHE_BLOCKS=4 \
  --set PS_FRAME_COUNT=16 --set IA_COMPACT_ENABLE=0 \
  --set SHARED_BANK_BYTES=4096 --set SHARED_BANK_COUNT=9 \
  --set IM2COL_CACHE_BYTES=16384 --set AXI_READ_OUTSTANDING=4 \
  --set PS_POOL_BYTES=32768 --set PS_FORCE_RAW=1 \
  --set CAPACITY_BUDGET_BYTES=81920 \
  --set CAPACITY_BUDGET_SCOPE=logical-state \
  --set CAPACITY_REPRESENTATION=raw32 --set CONV_LOW_LATENCY=1

"$TASK_PY" test/gemmini_comparison/run_storage_operators.py \
  --repo "$TASK_REPO" --reference-root "$TASK_REF" \
  --workloads "$TASK_REF/workloads" --out "$TASK_OUT/operators_fast" \
  --verilator "$TASK_VERILATOR" --jobs 2 \
  --bank-bytes 4096 --bank-count 9 --cache-bytes 16384 \
  --pe-count 16 --conv-low-latency

"$TASK_PY" test/gemmini_comparison/check_public_operators.py \
  --run "$TASK_OUT/operators_fast" --out "$TASK_OUT/comparison_fast" \
  --require-leading-gemm

"$TASK_PY" test/gemmini_comparison/prepare_regression_operators.py \
  --out "$TASK_OUT/numeric_workloads" --seed 20261123

"$TASK_PY" test/gemmini_comparison/run_storage_operators.py \
  --repo "$TASK_REPO" --reference-root "$TASK_REF" \
  --workloads "$TASK_OUT/numeric_workloads" --out "$TASK_OUT/numeric_fast" \
  --verilator "$TASK_VERILATOR" --jobs 2 \
  --bank-bytes 4096 --bank-count 9 --cache-bytes 16384 \
  --pe-count 16 --conv-low-latency

"$TASK_PY" test/gemmini_comparison/run_storage_models.py \
  --repo "$TASK_REPO" --out "$TASK_OUT/models_fast" \
  --prepared "$TASK_REF/prepared" \
  --gcc "$TASK_REF/tools/xpack-riscv-none-elf-gcc-14.2.0-3/bin/riscv-none-elf-gcc" \
  --verilator "$TASK_VERILATOR" --picorv32 "$TASK_REF/source/picorv32" \
  --shared-bank-bytes 4096 --shared-bank-count 9 --im2col-cache-bytes 16384 \
  --capacity-budget-bytes 81920 --capacity-report "$TASK_OUT/capacity_fast/result.json" \
  --arena-bytes 524288 --first-read-latency 8 --pe-count 16 \
  --conv-low-latency --jobs 2 --run-jobs 2 --samples 0 1 --modes hw --kinds perf trace
```

默认配置的容量命令使用 `--set CONV_LOW_LATENCY=0` 和 `--output-root "$TASK_OUT/capacity_registered"`。默认配置的算子与模型仿真命令移除 `--conv-low-latency`，并使用独立输出目录；模型命令使用 `--out "$TASK_OUT/models_registered"` 和 `--capacity-report "$TASK_OUT/capacity_registered/result.json"`。`check_public_operators.py` 对共同的 36 项算子检查数值、计时、配置与全部 31 项 GEMM 领先条件；26 项补充测试由 `run_storage_operators.py` 检查完整预期外存图像。

### 综合与静态时序复现

本次综合使用 Python 3.12.14、`pyosys==0.71.post40` 与其自带 ABC；OpenSTA 为 Debian 软件包 `0~20191111gitc018cb2+dfsg-1` 中的 2.0.17。工具和库文件的来源、版本、SHA-256 保存在 `data/performance_20261123/timing.json` 的 `tools` 字段。

将 `TASK_STA` 和 `TASK_LIB` 设置为相应文件路径。库文件可从固定的 [OpenROAD-flow-scripts 提交](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/82ac25be57125cc724388ef89f01ce65f9ba3dcc/flow/platforms/nangate45/lib/NangateOpenCellLibrary_typical.lib) 取得。以下命令从仓库根目录执行，使用独立目录保存两版映射及完成驱动选择后的时序结果。

```bash
TASK_REPO="$PWD"
TASK_OUT="$TASK_REPO/build/performance_20261123"
TASK_TOOLS="$TASK_OUT/open_timing_tools"
TASK_STA="/absolute/path/to/sta"
TASK_LIB="/absolute/path/to/NangateOpenCellLibrary_typical.lib"
python3 -m pip install --target "$TASK_TOOLS/python" pyosys==0.71.post40
export PYTHONPATH="$TASK_TOOLS/python:${PYTHONPATH:-}"

git worktree add --detach "$TASK_OUT/source_remote" \
  e6caf608e3aeca205b956908a38b4d229209529c

for TASK_REVISION in remote current
do
  TASK_SOURCE="$TASK_REPO"
  if [ "$TASK_REVISION" = remote ]
  then
    TASK_SOURCE="$TASK_OUT/source_remote"
  fi
  TASK_MAP="$TASK_OUT/mapping_$TASK_REVISION"

  python3 scripts/asic/map_standard_cells.py \
    --repo "$TASK_SOURCE" --out "$TASK_MAP" --liberty "$TASK_LIB" \
    --jobs 2 --target-ps 6000 --drive-cell BUF_X1 --output-load-ff 5 \
    --profiles ps_frame_store vector_engine \
      conv_descriptor_fast conv_descriptor_registered \
      conv_stream_fast conv_stream_registered

  python3 scripts/asic/map_standard_cells.py \
    --repo "$TASK_SOURCE" --out "$TASK_MAP/quantization" \
    --liberty "$TASK_LIB" --profiles vec_requant --abc-fast \
    --target-ps 6000 --drive-cell BUF_X1 --output-load-ff 5

  for TASK_PROFILE in ps_frame_store vector_engine \
    conv_descriptor_fast conv_descriptor_registered \
    conv_stream_fast conv_stream_registered vec_requant
  do
    TASK_MODULE_MAP="$TASK_MAP/$TASK_PROFILE"
    TASK_ENDPOINT_ARGS=()
    case "$TASK_PROFILE" in
      conv_descriptor_*)
        TASK_TOP=conv_im2col_descriptor
        TASK_CLOCK=i_clk
        TASK_RESET=i_rst_n
        ;;
      conv_stream_*)
        TASK_TOP=conv_im2col_stream
        TASK_CLOCK=i_clk
        TASK_RESET=i_rst_n
        ;;
      *)
        TASK_TOP="$TASK_PROFILE"
        TASK_CLOCK=clk
        TASK_RESET=rst_n
        ;;
    esac
    if [ "$TASK_PROFILE" = vec_requant ]
    then
      TASK_MODULE_MAP="$TASK_MAP/quantization/vec_requant"
      TASK_ENDPOINT_ARGS=(--report-output o_group_ready)
    fi

    python3 scripts/asic/resize_standard_cells.py \
      --sta "$TASK_STA" --liberty "$TASK_LIB" \
      --netlist "$TASK_MODULE_MAP/mapped.v" \
      --netlist-json "$TASK_MODULE_MAP/mapped.json" \
      --top "$TASK_TOP" --clock-port "$TASK_CLOCK" --reset-port "$TASK_RESET" \
      --out "$TASK_OUT/timing_$TASK_REVISION/$TASK_PROFILE" \
      "${TASK_ENDPOINT_ARGS[@]}"
  done
done
```

`resize_standard_cells.py` 使用本报告的 150 MHz 约束，调用 `run_opensta.py` 保存每次分析的 SDC、完整路径、动态端点检查和转换时间结果，最后输出保持连接不变的标准单元驱动选择。`--abc-fast` 选择已经记录的显式 `map` 序列，映射全部内部组合与顺序逻辑。

工具自身的实际运行检查可由以下命令复现：

```bash
python3 test/opensta_analysis/run.py \
  --sta "$TASK_STA" --liberty "$TASK_LIB" --out "$TASK_OUT/opensta_tool_test"
python3 test/standard_cell_resize/run.py \
  --sta "$TASK_STA" --liberty "$TASK_LIB" --out "$TASK_OUT/drive_selection_test"
```

## 10. 文件与来源

| 文件 | 内容 |
| --- | --- |
| [operators.csv](data/performance_20261123/operators.csv) | 36 项形状、原始与优化后周期、公开比较对象周期 |
| [operators.json](data/performance_20261123/operators.json) | 数值条件、硬件配置、逐项输出摘要与自动调度选择 |
| [capacity.json](data/performance_20261123/capacity.json) | 两种配置的完整逻辑状态统计 |
| [component_tests.json](data/performance_20261123/component_tests.json) | 部分和、向量、量化及软件调度检查 |
| [models.csv](data/performance_20261123/models.csv) | 四个完整模型的平均推理周期 |
| [models.json](data/performance_20261123/models.json) | 模型数值、逐张量检查及编译输入摘要 |
| [timing.csv](data/performance_20261123/timing.csv) | 七种模块配置的时序与面积估计 |
| [timing.json](data/performance_20261123/timing.json) | 工艺、约束、映射、时序与源码检查 |
| [nvdla_ar2.csv](data/performance_20261123/nvdla_ar2.csv) | NVDLA 独立条件下的 6 项逐项结果 |

公开实现使用固定版本：[Gemmini-BiRD](https://github.com/dwconv/gemmini-dwconv/tree/4a33b75f975297e309847f41f81f4c0f8b20b81d)、[VTA](https://github.com/apache/tvm-vta/tree/d4a15f627d5cc9762a82270d1be60a136e6af9c2)、[Google Coral NPU](https://github.com/google-coral/coralnpu/tree/f385a31b4af454be21063fca1d17351b35a3a99c)、[NVDLA](https://github.com/nvdla/hw/tree/1a65f1f5b48268accaa47c95f95c2601918be095)。公开对象的固定测量值及输入形状保存在 `test/gemmini_comparison/public_operator_reference_20261123.json`。本次对最终合并的 NPU 源码重新构建并运行全部算子；公开对象采用同一参考实验已验证的逐项结果。


## 11. 导入提交

提交分支为 `perf/accelerator-20261123`，bundle 的必要父提交为 `e6caf608e3aeca205b956908a38b4d229209529c`。在已经取得该远端提交的仓库中执行：

```bash
git bundle verify /absolute/path/to/mini_tflm_dsa_performance_20261123.bundle
git fetch /absolute/path/to/mini_tflm_dsa_performance_20261123.bundle \
  refs/heads/perf/accelerator-20261123:refs/heads/perf/accelerator-20261123
git switch perf/accelerator-20261123
```

性能比较中的低延迟配置使用 `CONV_LOW_LATENCY=1`，默认配置为 `CONV_LOW_LATENCY=0`。两种配置的 GEMM 结果相同。
