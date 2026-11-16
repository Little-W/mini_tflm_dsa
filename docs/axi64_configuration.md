# 64 位 AXI 与 Gemmini 比较配置

本配置用于性能版 PicoRV32、本项目 NPU 和第三方 DWConv Gemmini 的比较。
加速器与共享 RAM 之间的 AXI 数据总线为 **64 位**，每个完整数据拍传输 **8 字节**。
INCR 突发遵守 AXI4 的 **256 拍**和 **4 KiB 地址边界**要求，64 位总线对应最多
2048 字节的完整宽度突发。逻辑 DMA 描述符可以覆盖更大的数据范围，由硬件产生多个突发。

## 1. 总线与主存

| 项目 | NPU | Gemmini |
| --- | --- | --- |
| AXI `RDATA`、`WDATA` | 64 位 | 64 位 |
| `WSTRB` | 8 位 | 8 位 |
| `ARLEN`、`AWLEN` | 8 位 | 8 位 |
| 完整数据拍 `AxSIZE` | 3 | 3 |
| 最大 INCR 突发拍数 | 256 | 256 |
| 突发地址边界 | 4 KiB | 4 KiB |
| 加速器未完成读、写请求 | 各 4 | 各 4 |
| 系统 RAM | 2 MiB | 2 MiB |
| RAM 最早首拍延迟 | 8 周期 | 8 周期 |
| 连续读数据吞吐 | 每周期 1 拍 | 每周期 1 拍 |
| 就绪突发之间的空闲周期 | 0 | 0 |
| RAM 附加固定延迟 | 0 | 0 |

完整模型共用 `soc_top` 中的 PicoRV32、地址仲裁、时序缓冲和 `soc_axi_ram`。
CPU 原生接口、CPU AXI 接口和 AXI-Lite 寄存器接口保持 32 位。
互连根据字节地址选择共享 64 位总线中的低 32 位或高 32 位，并转换字节使能。
CPU 指令缓存保持 64 行、每行 4 个 32 位字，共 1 KiB。

`CPU_MEM_DP` 以 32 位字为单位表示主存容量。64 位 RAM 的物理行数为
`CPU_MEM_DP × 32 / BUS_WIDTH`，因此总线扩展后主存仍为 2 MiB。
RAM 根据 `AxSIZE` 和 `AxBURST` 推进字节地址，支持窄传输、部分字节写入和独立读写。

模型固件和输入文件采用稀疏 32 位内存镜像。运行程序先按字地址合并固件与数据，
再按小端格式组成 64 位 RAM 行。这样可以保留同一行中的两个 32 位字，
包括仅覆盖其中一个字的输入文件。原文件和实际加载文件均记录 SHA-256。

## 2. 同步读取与首拍延迟

主要比较使用 8 周期最早首拍延迟、每周期一个 64 位数据拍，以及每个加速器最多
4 个未完成读请求。RAM 的数据读取发生在时钟上升沿，读结果经过寄存器返回。
后续请求的等待可以与当前突发的数据返回重叠。

首拍延迟 `L` 从 RAM 接口接受地址的上升沿开始计算，即 `ARVALID && ARREADY`。
当 RAM 读通道空闲且 `RREADY=1` 时，在第 `L` 个后续上升沿完成首个数据握手。
每个请求分别保存就绪时间，计数从该请求的 AR 握手开始。
对按序返回、每周期一拍且接收端持续就绪的请求，有：

\[
t_{\mathrm{first},i}
=\max(t_{\mathrm{AR},i}+L,\;t_{\mathrm{last},i-1}+1).
\]

后续请求已就绪时，前一个突发的 `RLAST` 与下一个突发的首拍在相邻上升沿传输，
两者之间有 **0 个空闲周期**。例如 `L=8`，在周期 0 和 4 接受两个四拍突发，
分别在周期 8 至 11、12 至 15 返回，八个数据拍连续传输。
若读通道仍被占用、接收端暂停或地址尚未被接受，实际首拍时间相应后移。

| 接口 | 参数 | 含义 |
| --- | --- | --- |
| SoC RTL | `RAM_READ_FIRST_LATENCY` | 传入同步 RAM 的最早首拍周期数，至少为 1 |
| RAM RTL | `READ_FIRST_LATENCY` | 从本模块 AR 握手至首个 R 握手的最早周期数 |
| 模型构建程序 | `--first-read-latency 8` | 同时记录构建配置并设置 RTL 参数 |
| RAM 仿真运行参数 | `+RAM_READ_FIRST_LATENCY=8` | 设置本次仿真的精确首拍延迟 |
| 独立算子 | `--first-read-latency 8` | 双方相同的逐请求首拍延迟 |
| Gemmini 独立算子 | `--inter-burst-gap-cycles 1` | 相邻突发边界上两个数据握手相差一个周期，即没有空闲周期 |
| NPU 独立算子 | `--memory-timing pipelined` | 各请求独立等待就绪，相邻就绪突发连续返回 |

比较报告程序使用 `--inter-burst-gap 1` 检查两组测量的相邻突发时序。
完整模型的 `--latency` 控制附加等待，主要比较设为 0；
精确首拍延迟通过 `--first-read-latency` 设置。

RAM 记录首拍实际延迟的最小值、最大值和请求数量。SoC 中地址仲裁和时序缓冲还会
影响加速器自身接口观察到的延迟，因此最早首拍参数的测量位置固定为 RAM 接口。
测试分别检查空闲请求的精确延迟、多个在途请求、相邻突发连续返回和接收端暂停。

独立 GEMM、Conv 和 DW 均从空闲硬件和冷缓存开始，计入输入读取、计算、输出写回
及所有 AXI 响应完成的周期。完整模型共用生产 SoC RAM，逐层周期还包括 Pico 上的
命令组织和算子处理。独立算子与完整模型分别报告。

## 3. 主要数据 RAM

NPU 使用 `SIZE=16`、`IA_CACHE_BLOCKS=8`、`PS_FRAME_COUNT=16`、
`PS_STORAGE_ROWS=720` 和 `OA_S16_FIFO_BANKS_MAX=4`。

| NPU 数据数组 | 计算方法 | 容量 |
| --- | --- | ---: |
| 部分和 | `720 × 16 × 32 / 8` | 46,080 B |
| IA | `8 × 16 × 16 × 16 / 8` | 4,096 B |
| 权重双 tile | `2 × 16 × 16 × 16 / 8` | 1,024 B |
| S8 输出 FIFO | `32 × 16 × 16 × 8 / 8` | 8,192 B |
| S16 输出 FIFO | `4 × 16 × 16 × 16 / 8` | 2,048 B |
| 共享卷积缓存 | `128 × 2 × 16` | 4,096 B |
| **主要数据 RAM 合计** | | **65,536 B** |

Gemmini 使用 32 KiB scratchpad 和 32 KiB accumulator，共 65,536 B。
其硬件 Im2Col 和 DW 数据流共用这些存储。2048 字节 DMA 配置还包含
2048 字节读合并数据寄存器、2048 字节写数据寄存器及 64 字节单块写寄存器，
共 4160 字节。其 DW 部分和寄存器为 `256 × 20 bit = 640 B`。

主要数据 RAM 的容量比较包含 NPU 的共享窗口缓存。
参数表、缓存标记、需求队列、预取描述、流水寄存器和 PE 寄存器分别计算。
NPU 的四项 DMA 返回描述符保存 604 bit 元数据，按字节计约为 76 B；
同步部分和读写的数据转发使用 512 bit 数据寄存器及有效位。
权重双缓冲和连续偏置预取复用已有数据存储。
NPU 的矩阵操作数内部通路为 16 位，Gemmini 为 8 位；相同的阵列维度和主要 RAM 容量
提供了计算和存储配置比较，面积、功耗及最高工作频率需要通过综合和实现测量。

## 4. DMA 与驱动

`DMA_MAX_BYTES` 默认由 `256 × (BUS_WIDTH / 8)` 计算，并传递到读写 DMA、
卷积读取器和相关顶层模块。读写请求生成器同时处理 256 拍限制和 4 KiB 边界。
64 位填充可以在一个周期内更新卷积缓存的两个 32 位存储部分。
S8 数据每拍最多装载 8 个元素，S16 数据每拍最多装载 4 个元素，
偏置和量化参数每拍最多装载两个 32 位值。

| 只读寄存器 | 字节偏移 | 返回值 |
| --- | ---: | --- |
| `NPU_REG_DMA_MAX_BYTES` | `0x0f0` | 最大突发字节数，64 位时为 2048 |
| `NPU_REG_AXI_DATA_BITS` | `0x0f4` | 物理 AXI 数据位宽，当前为 64 |

驱动将 `axi_data_bits` 和 `dma_max_bytes` 传入 WS/IS 及复用参数搜索。
`read_beats`、`write_beats` 使用物理数据拍数；`read_words`、`write_words`
继续以 32 位字计数，便于检查逻辑数据流量。请求数量按突发长度和页面边界计算。
完整 SoC 固件使用 `DSA_SCHEDULE_READ_BEAT_CYCLES=1`，独立测试按所选内存服务显式传入拍间隔。

Gemmini 使用实际硬件生成的参数头，`MAX_BYTES=2048`。
DMA 完成字节计数为 16 位，完成通知可以表示整个 2048 字节请求。
固定版本、构建补丁、生成 RTL、参数头和可执行文件的 SHA-256 保存于构建记录。

## 5. PicoRV32 与数值计算

| 项目 | 测试配置 |
| --- | --- |
| ISA | RV32IM，关闭压缩指令 |
| 乘法、除法 | `ENABLE_MUL=1`、`ENABLE_FAST_MUL=1`、`ENABLE_DIV=1` |
| 寄存器读端口 | `ENABLE_REGS_DUALPORT=1` |
| 移位 | `BARREL_SHIFTER=1`、`TWO_STAGE_SHIFT=1` |
| 运算延迟选项 | `TWO_CYCLE_COMPARE=0`、`TWO_CYCLE_ALU=0` |
| 指令缓存 | 1 KiB |
| C/C++ 编译 | `-O3 -march=rv32im_zicsr -mabi=ilp32` |
| 模型数值 | INT8 输入、权重和输出，INT32 累加，Q31 最近偶数舍入 |

完整模型验证实际零点、逐通道参数、偏置、激活范围及每个中间张量。
Gemmini 的完整模型适配输出 INT32，随后由 Pico 完成精确重新量化；这些周期计入 `Invoke`。
独立算子使用双方相同且可精确表示的缩放参数，直接比较计算与 DMA。

## 6. 运行

```bash
python3 test/model_benchmark/run_suite.py \
  --out build/axi64/models \
  --prepared /absolute/path/to/prepared \
  --gcc riscv-none-elf-gcc --verilator verilator \
  --picorv32 /absolute/path/to/picorv32 \
  --cpu-profile performance --icache 1 --bus-width 64 \
  --ia-cache-blocks 8 --ps-storage-rows 720 --s16-output-banks 4 \
  --first-read-latency 8 --latency 0 --jobs 2 --run-jobs 4
```

每个模型使用两个输入，运行软件、硬件两种模式的普通固件和逐层记录固件，共 32 次。
普通固件以 `rdcycle` 测量完整 `Invoke`；初始化单独报告。
第三方 Gemmini 的完整模型运行方法见
[模型适配说明](../test/gemmini_comparison/model_runtime/README.md)。

Dense 的每项性能条件为 `6 × NPU周期 <= 5 × Gemmini周期`，对应至少 1.2 倍加速。
独立测试列出五个真实 FC 层的归属和 `vector_m1`，相同矩阵形状共用同一次可复现测量。
Gemmini 的完整命令计时和首次 loop 执行命令到完成的计时分别检查，二者均须达到目标。
完整模型逐层测试同时检查两个输入，并采用该层两种 Gemmini 策略中较短的时间。

协议定义参考 Arm 的
[AMBA AXI and ACE Protocol Specification](https://documentation-service.arm.com/static/5f915bbcf86e16515cdc3b23)。
