# DMA 返回条件与任务接收

本目录验证 `npu_top` 的最终就绪判断，以及权重加载器和仲裁器为该判断提供的两个布尔输出。参考源码为 `7ef39f0101ebf39184d11dbdc80a4042faee75c2`。当前 RTL 的 SHA-256、正式证明、数值结果和局部映射统计保存在 `measurement.json`。

## 当前设计

权重加载器通过 `o_prefetch_quiescent` 输出原有后台空闲条件 `load_idle_i_quiescent`。该条件包含预取状态、正在传输标志、等待比较的预取请求、DMA 忙状态和响应位置占用状态。

仲裁器通过 `o_kernel_eligible` 输出权重命令的资格条件：命令位置可用，并且当前命令属于 `C_KERNEL`。公开的 `kernel_granted` 继续在该条件上检查当前 `abort`。两个新增端口均为一位组合输出。

令 `Q` 表示后台空闲，`R` 表示加载器原始的 `load_weight_req`，`G` 表示上述命令资格，`A` 表示原有的其他接收条件。最终就绪条件使用以下关系：

```text
kernel_granted = !abort && G
kernel_prefetch_idle = Q && !(R && kernel_granted)
sa_ready = A && Q && (abort || !(R && G))
```

顶层提前计算 `R && G`，把 `abort` 直接接入最终 LUT6。该 LUT 的输入依次为 `Q`、IA 预取空闲、状态空闲检查、就绪状态检查、`R && G` 和 `abort`，`INIT` 为 `64'h8000_8000_0000_8000`。

`cfg_start_event`、原有授予、DMA 开始、预取空闲、完成输出和状态更新保持原有语义。公开 `calc_start` 继续接受任意输入值。生产环境中 AXIL 开始请求包含 `sa_ready` 的实际表达式也纳入连接证明和局部测量。

## 正式验证

实际组合连接包含总线读写错误、完成错误、顶层故障和中止、五个客户端授予、权重加载器开始和空闲、AXIL 开始以及 NPU 配置与向量启动条件。

- 通用与 FPGA 两种实现，量化客户端开关及 clock-gating 开关，共 8 组 SAT 证明全部通过。
- 输入未附加限制，覆盖全部 8 种客户端编码、命令位置占用的两种取值、当前中止和全部读写错误来源。
- 完整仲裁器在 FPGA BUS32/64/128 与量化开关组合，以及通用 BUS64 下比较，共 7 组、13,179 位通过。每组显式观察全部 297 个状态位和全部 DMA 端口。
- 完整权重加载器共 4 组、49,060 位通过。SIZE/COUNT_WIDTH/BUS_WIDTH 配置为 4/8/32、16/32/64、16/29/32、16/29/64，后两组使用官方 FPGA 原语模型。每组比较全部公开输出及所有存储状态。
- 两个模块的原有实现经结构核对保持逐字一致，仅增加组合输出及其赋值。正式比较不限制初始状态、复位输入或状态编码。

两个既有权重测试模块为新增输出声明了对应信号，继续使用原有端口自动连接和测试内容。

## 数值回归

全部回归均启用 UBSan，并使用官方 FPGA 原语模型。

| 范围 | 结果 |
|---|---:|
| 权重预取 BUS64，COUNT_WIDTH=29 | 29,443 周期 |
| 权重数值检查 | 72,960 个值 |
| 权重 DMA 开始及完成 | 各 312 次 |
| 已发送数据块 | 285 个 |
| 命中 / 丢弃 | 73 / 25 次 |
| 刷新场景 | 4 组 |
| DMA BUS32 | 21 场景、905 检查 |
| DMA BUS64 | 21 场景、905 检查 |

每种 DMA 总线宽度均覆盖 15 次描述符取消、5 次同周期释放、5 次授予撤销和 8 次四个上下文占满检查，最短命令接受间隔为两个周期。

## 实际连接映射

测量保留实际读保护、读通道复用、模式寄存器、写保护及 SoC R/B 返回缓冲。上下文计数、客户端编码和其余模块提供的状态作为测量输入寄存器。原始上下文非空表达式取自 `axi_linear_block_dma.sv`，并连接到实际读保护输入。返回数据排列核对实际 SoC 缓冲的表达式。

映射使用 physical-cost、8 输入逻辑分解、6,667 ps 目标、300 ps 连线估计。参考和当前映射均通过 ABC9 组合等价检查；完整局部网表可以分析，无未识别原语或组合环。

| 项目 | 参考 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 1,101 | 1,100 |
| FF | 1,524 | 1,524 |
| `rd_context_count → sa_ready` | 8 | 6 |
| `rd_context_count → cfg_start_event` | 10 | 8 |
| `rd_context_count → vector start` | 10 | 8 |
| 写保护状态 → `sa_ready` | 8 | 6 |
| 写保护状态 → `cfg_start_event` / `vector start` | 10 | 8 |
| R 返回缓冲 → `sa_ready` | 6 | 4 |
| B 返回缓冲 → `sa_ready` | 7 | 5 |
| 读写完成或错误 → `sa_ready` | 6 | 4 |
| `abort_pending → sa_ready` | 4 | 2 |

共检查 37 类来源与 13 类终点，所有组合级数均未增加。原有五客户端授予、权重开始和权重预取空闲路径保持相同级数。

本次局部测量的上下文非空表达式映射为一级；固定 R23 整机的同一表达式映射为两级。局部结果记录相同测量结构之间的两级减少。完整 SoC 的最终级数由整合后的固定源码重新计算。

该局部测量没有执行整机的 740 个 DSP 分配，写保护地址自增的局部最长路径在两版中均为 18 级。150 MHz 需要完整厂商布线后静态时序分析确认。

## 复现

在已配置仓库开源 FPGA 工具的环境执行：

```bash
python3 test/npu_admission_r23/run_formal.py \
  --out build/npu_admission_r23/formal_complete
python3 test/npu_admission_r23/prepare_measurement.py \
  --out build/npu_admission_r23/inputs \
  --formal build/npu_admission_r23/formal_complete
python3 scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config build/npu_admission_r23/inputs/cases.json \
  --cases reference current --through pre_lut --out build/npu_admission_r23/pre
python3 scripts/fpga/remap_fpga_luts.py \
  --source build/npu_admission_r23/pre/reference \
  --out build/npu_admission_r23/cost/reference \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 --max-lut-inputs 8
python3 scripts/fpga/remap_fpga_luts.py \
  --source build/npu_admission_r23/pre/current \
  --out build/npu_admission_r23/cost/current \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 --max-lut-inputs 8
python3 test/npu_admission_r23/measure_paths.py \
  --mapped build/npu_admission_r23/cost --pre build/npu_admission_r23/pre \
  --out build/npu_admission_r23/paths.json
python3 test/kernel_prefetch/run.py --out build/npu_admission_r23/kernel_numeric \
  --verilator verilator-modern --bus-width 64 --count-width 29 --fpga
python3 test/dma_read_permission/run_numeric.py \
  --out build/npu_admission_r23/dma_numeric --verilator verilator-modern
python3 test/npu_admission_r23/collect_report.py --build build/npu_admission_r23 \
  --out test/npu_admission_r23/measurement.json
```

并行协作时，为综合与映射命令提供相同的 `--lock-file`，保持计算任务串行执行。报告收集程序逐项核对受测源码、生成的测量源码、证明及数值摘要、映射网表和技术映射输入的 SHA-256。
