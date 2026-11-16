# 原生 AXI64 独立算子比较：首拍 8 周期，每周期一个读数据拍

双方使用 64 bit AXI 数据端口、256 拍最大突发和 4 KiB 边界拆分，单次完整数据宽度事务最多 2,048 B。主要数据 RAM 均为 65,536 B。31 个 GEMM、5 个 NPU Conv/DW，以及 Gemmini 的两组 Conv/DW 均通过完整输出验证。[^npu_gemm][^npu_conv][^gemmini_gemm][^gemmini_native][^gemmini_im2col]

GEMM 逐项领先目标通过 **31/31 项**，每项均直接检查 `NPU 周期 < Gemmini 周期`。

按完整命令计时，Dense 目标通过 **6/6 项**；同时要求首条循环启动计时也达到目标的严格检查通过 **6/6 项**。每项独立使用整数条件 `6 × NPU 周期 ≤ 5 × Gemmini 周期`，对应至少 1.2×。五个 FC 层按其真实模型尺寸和节点归属列出；MNIST 的第二个 FC 与 ResNet 的 FC 共用同一尺寸测量。本组输入与权重为共同生成的整数张量，完整模型的真实输入、权重和逐层量化测试另行统计。

## 1. 硬件与内存服务

| 项目 | mini_tflm_dsa | DWConv Gemmini |
|---|---|---|
| 矩阵阵列 | 16 × 16 | 16 × 16 |
| 外部输入 / 权重 / 输出 | INT8 / INT8 / INT8 | INT8 / INT8 / INT8 |
| 矩阵乘法器输入 / 累加结果 | INT16 / INT32 | INT8 / INT32 |
| 主要数据 RAM | 60 KiB + 4 KiB window cache | 32 KiB SP + 32 KiB ACC |
| AXI 数据宽度 / 最大突发 | 64 bit / 256 拍 | 64 bit / 256 拍 |
| 首个空闲读响应延迟 | 8 周期 | 8 周期 |
| 同一读突发的数据拍间隔 | 1 周期 | 1 周期 |
| 已成熟请求之间的读突发转换间隔 | 最少 1 周期 | 最少 1 周期 |
| 配置的读 / 写并发请求 | 4 / 4 | 4 / 4 |
| 内存服务同时处理的写事务 | 1 | 1 |
| 写数据拍间隔 | 最少 1 周期 | 最少 1 周期 |
| AW 至首个 W，末个 W 至 B | 各最少 1 周期 | 各最少 1 周期 |
| 输出量化 | ×1/32，最近偶数舍入 | ×1/32，最近偶数舍入 |

每次算子测试重新启动仿真并复位加速器。NPU 从接受 `calc_start` 开始计时，Gemmini 从第一个计时配置命令开始，经过最终 `FENCE` 结束。两者均计入硬件数据搬运、计算、重新量化和输出写回，并等待全部内存响应。主机指令、布局准备与调度搜索位于本组独立算子计时之外。Gemmini GEMM 固定使用上游 WS 自动分块；普通卷积同时测量优化后的原生 `LoopConv` 和真实启用的独立 `Im2Col`，DW 使用第三方专用指令。[^gemmini_build]

每个请求在 AR 握手周期独立记录最早响应时间 `t_AR + 8`。后续请求可以在前一突发传输期间等待成熟；已经成熟的请求按表中突发转换间隔继续返回，因此多个 outstanding 请求能够隐藏首拍等待。内存数据在时钟边沿读取并进入响应寄存器。突发转换间隔表示前一突发最后一个 R 握手边沿与后一突发第一个 R 握手边沿的周期差；间隔为 1 时，两次握手位于相邻周期，中间没有空闲的数据拍。

参考源代码及构建依赖由构建清单中的提交号和 SHA-256 标识。Gemmini 的 DMA 完成字节计数使用 16 bit，支持到 2,048 B 的事务；相应源代码补丁和编译源文件的 SHA-256 随清单保存。[^gemmini_build]

## 2. Dense 逐项 1.2× 目标

| 模型 / 节点 | M × N × K | NPU 周期 | Gemmini 周期 | 加速比 | NPU 周期上限 | 达到 1.2× |
|---|---:|---:|---:|---:|---:|---|
| MNIST CNN / 5 | 1 × 64 × 784 | 6,500 | 7,822 | 1.20338× | 6,518 | 通过 |
| MNIST CNN / 6 | 1 × 10 × 64 | 213 | 766 | 3.59624× | 638 | 通过 |
| MobileNetV1 VWW / 29 | 1 × 2 × 256 | 441 | 1,285 | 2.91383× | 1,070 | 通过 |
| ResNet-8 CIFAR-10 / 14 | 1 × 10 × 64 | 213 | 766 | 3.59624× | 638 | 通过 |
| DS-CNN KWS / 11 | 1 × 12 × 64 | 228 | 727 | 3.18860× | 605 | 通过 |
| vector_m1 | 1 × 64 × 64 | 656 | 853 | 1.30030× | 710 | 通过 |

### Gemmini 首条循环启动命令的补充计时

主表采用 Gemmini 从首条计时配置命令到最终完成的周期。下表同时给出从首条循环启动命令 `first_launch_cycle` 到完成的周期，NPU 仍从接受 `calc_start` 开始计时。两种起点均保留原始测量值。[^gemmini_gemm]

| 模型 / 节点 | Gemmini 首条循环启动周期 | Gemmini 启动至完成 | NPU 周期 | 加速比 | NPU 周期上限 | 达到 1.2× |
|---|---:|---:|---:|---:|---:|---|
| MNIST CNN / 5 | 11 | 7,811 | 6,500 | 1.201692× | 6,509 | 通过 |
| MNIST CNN / 6 | 11 | 755 | 213 | 3.544601× | 629 | 通过 |
| MobileNetV1 VWW / 29 | 11 | 1,274 | 441 | 2.888889× | 1,061 | 通过 |
| ResNet-8 CIFAR-10 / 14 | 11 | 755 | 213 | 3.544601× | 629 | 通过 |
| DS-CNN KWS / 11 | 11 | 716 | 228 | 3.140351× | 596 | 通过 |
| vector_m1 | 11 | 842 | 656 | 1.283537× | 701 | 通过 |

该补充计时达到 1.2× 的项目为 **6/6**。JSON 分别保存完整命令周期与循环启动周期，不将二者混用。

表中加速比为 `Gemmini 周期 / NPU 周期`。`dense_target.passed` 保存完整命令计时的目标结果，`dense_target.strict_passed` 要求两种起点均满足目标。输入、输出与实验条件通过验证记录为 `comparison_verified`；`all_requested_targets_passed` 同时要求实验条件、全部 GEMM 领先和严格 Dense 目标通过。[^npu_gemm][^gemmini_gemm]

### 长 FC 的读带宽约束

MNIST 第一个 FC 的输入为 784 B、权重为 50,176 B、INT32 偏置为 256 B，冷启动至少读取 51,216 B，即 6,402 个 8 B 数据拍。本组读服务需要至少 6,402 个周期的传输时间；完整命令计时下的 1.2× 目标要求 NPU 不超过 6,518 周期。
同时满足首条循环启动计时的严格目标要求 NPU 不超过 6,509 周期。
目标上限比必要读传输时间多 107 周期。可用空间还需要容纳首个响应、突发转换、计算和输出写回；实际结果由完整算子计时给出。

上述传输时间按每个读数据拍占用完整服务间隔计算，不包含命令等待、首个响应和跨突发间隔。逻辑 MAC 数除以峰值与总周期得到的是吞吐利用率；带宽受限时，该数值较低仍可能伴随持续的数据读取。

该 FC 实测从第 20 周期到第 6,421 周期连续返回 6,402 个读数据拍，最大同时有 4 个未完成读事务。6,500 个总周期比必要读服务时间多 98 个周期；该差值反映全任务时间与必要读传输时间的差额，计算和写回可以与读取重叠。[^npu_gemm]

## 3. 全部 GEMM

| 名称 | M × N × K | NPU 周期 | Gemmini 周期 | 加速比 | NPU 数据流 |
|---|---:|---:|---:|---:|---|
| `tile16` | 16 × 16 × 16 | 260 | 360 | 1.3846× | WS |
| `tile32` | 32 × 32 × 32 | 550 | 821 | 1.4927× | WS |
| `tile64` | 64 × 64 × 64 | 2,295 | 3,166 | 1.3795× | WS |
| `tail17` | 17 × 23 × 19 | 521 | 2,070 | 3.9731× | WS |
| `vector_m1` | 1 × 64 × 64 | 656 | 853 | 1.3003× | WS |
| `model_m784_n8_k9` | 784 × 8 × 9 | 3,691 | 11,222 | 3.0404× | IS |
| `model_m196_n16_k72` | 196 × 16 × 72 | 3,496 | 9,980 | 2.8547× | WS |
| `model_m1_n64_k784` | 1 × 64 × 784 | 6,500 | 7,822 | 1.2034× | WS |
| `model_m1_n10_k64` | 1 × 10 × 64 | 213 | 766 | 3.5962× | WS |
| `model_m2304_n8_k27` | 2304 × 8 × 27 | 13,551 | 61,444 | 4.5343× | WS |
| `model_m2304_n16_k8` | 2304 × 16 × 8 | 12,815 | 19,452 | 1.5179× | IS |
| `model_m576_n32_k16` | 576 × 32 × 16 | 2,839 | 6,665 | 2.3477× | WS |
| `model_m576_n32_k32` | 576 × 32 × 32 | 4,396 | 7,545 | 1.7163× | WS |
| `model_m144_n64_k32` | 144 × 64 × 32 | 2,805 | 4,340 | 1.5472× | IS |
| `model_m144_n64_k64` | 144 × 64 × 64 | 4,325 | 5,540 | 1.2809× | IS |
| `model_m36_n128_k64` | 36 × 128 × 64 | 2,996 | 8,685 | 2.8989× | WS |
| `model_m36_n128_k128` | 36 × 128 × 128 | 5,137 | 13,939 | 2.7135× | WS |
| `model_m9_n256_k128` | 9 × 256 × 128 | 6,242 | 19,336 | 3.0977× | IS |
| `model_m9_n256_k256` | 9 × 256 × 256 | 12,162 | 17,942 | 1.4753× | IS |
| `model_m1_n2_k256` | 1 × 2 × 256 | 441 | 1,285 | 2.9138× | WS |
| `model_m125_n64_k40` | 125 × 64 × 40 | 3,238 | 6,457 | 1.9941× | WS |
| `model_m125_n64_k64` | 125 × 64 × 64 | 3,922 | 4,625 | 1.1792× | WS |
| `model_m1_n12_k64` | 1 × 12 × 64 | 228 | 727 | 3.1886× | WS |
| `model_m1024_n16_k27` | 1024 × 16 × 27 | 6,811 | 28,851 | 4.2359× | WS |
| `model_m1024_n16_k144` | 1024 × 16 × 144 | 29,099 | 81,891 | 2.8142× | WS |
| `model_m256_n32_k144` | 256 × 32 × 144 | 8,338 | 22,208 | 2.6635× | WS |
| `model_m256_n32_k288` | 256 × 32 × 288 | 16,222 | 42,364 | 2.6115× | WS |
| `model_m256_n32_k16` | 256 × 32 × 16 | 1,498 | 3,577 | 2.3879× | WS |
| `model_m64_n64_k288` | 64 × 64 × 288 | 7,615 | 12,221 | 1.6049× | WS |
| `model_m64_n64_k576` | 64 × 64 × 576 | 14,455 | 18,780 | 1.2992× | WS |
| `model_m64_n64_k32` | 64 × 64 × 32 | 1,535 | 2,386 | 1.5544× | WS |

## 4. Conv 与 DW

| 算子 | NPU 周期 | Gemmini 原生调度 | Gemmini 独立 Im2Col 组 | 相对原生调度 | 相对 Im2Col 组 |
|---|---:|---:|---:|---:|---:|
| `conv3x3_s2_96_c3_o8` | 54,633 | 87,231 | 176,021 | 1.5967× | 3.2219× |
| `dw3x3_s1_48_c8` | 44,025 | 34,438 | 34,438 | 0.7822× | 0.7822× |
| `dw3x3_s2_48_c8` | 11,468 | 18,239 | 18,239 | 1.5904× | 1.5904× |
| `conv3x3_32_c16_o16` | 57,409 | 25,582 | 58,908 | 0.4456× | 1.0261× |
| `conv3x3_8_c64_o64` | 26,743 | 40,746 | 65,466 | 1.5236× | 2.4480× |

DW 在两组中均走第三方专用 DW 指令；独立 Im2Col 对应普通卷积的硬件输入重排。JSON 保存每项实际 `loop_depthwise_launches`、`loop_conv_launches` 与独立 Im2Col 请求、响应计数。

## 5. 汇总与总线流量

| 算子集合 | 项数 | NPU 领先项数 | 总周期加速比 | 几何平均加速比 |
|---|---:|---:|---:|---:|
| `gemm` | 31 | 31 | 2.3892× | 2.1309× |
| `conv_native` | 5 | 3 | 1.0616× | 1.0616× |
| `conv_im2col` | 5 | 4 | 1.8174× | 1.5871× |
| `all_native` | 36 | 34 | 1.6979× | 1.9344× |
| `all_im2col` | 36 | 35 | 2.0915× | 2.0455× |

总周期加速比对应所列算子各执行一次；几何平均加速比对每项算子等权。JSON 保留各算子的完整周期、首个 AR 到完成、首个 AR 到最后 B 的时间区间，主要比较始终使用完整周期。

| Dense 形状 | NPU 读字节 / 拍 / 事务 | Gemmini 读字节 / 拍 / 事务 | NPU 写字节 / 拍 | Gemmini 写字节 / 拍 |
|---|---:|---:|---:|---:|
| `model_m1_n64_k784` | 51,216 / 6,402 / 258 | 52,560 / 6,570 / 791 | 64 / 8 | 64 / 8 |
| `model_m1_n10_k64` | 744 / 93 / 9 | 4,224 / 528 / 66 | 10 / 2 | 10 / 2 |
| `model_m1_n2_k256` | 776 / 97 / 33 | 2,312 / 289 / 258 | 2 / 1 | 2 / 1 |
| `model_m1_n12_k64` | 880 / 110 / 9 | 3,712 / 464 / 66 | 12 / 2 | 12 / 2 |
| `vector_m1` | 4,416 / 552 / 22 | 4,672 / 584 / 66 | 64 / 8 | 64 / 8 |

## 6. 复现与数据文件

比较程序检查共同输入和输出 SHA-256、完整输出结果、仿真器与构建清单、参数头、读写事务排空、实际数据拍计数、最大突发、内存服务间隔以及 Im2Col/DW 活动。

```bash
python3 test/gemmini_comparison/compare_axi64_operators.py --data-root /workspace/scratch/dc14ec427142 --npu-gemm /workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/npu_gemm/summary.json --npu-conv /workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/npu_conv/summary.json --gemmini-gemm /workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_gemm_results/results.json --gemmini-native /workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_conv_native/results.json --gemmini-im2col /workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_conv_im2col/results.json --gemmini-build /workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_build/generated_sp32_acc32_axi64_spdelay1/build_manifest.json --gemmini-gemm-traces /workspace/scratch/dc14ec427142/measurements/axi64/gemmini_gemm_traces --conv-workloads /workspace/scratch/dc14ec427142/comparison_conv_workloads_five --read-beat-cycles 1 --first-read-latency 8 --inter-burst-gap 1
```

添加 `--require-dense-target` 可在任一 Dense 项未同时满足两种起点下的 1.2× 目标时返回非零状态；`--require-all-targets` 同时要求全部 GEMM 领先。JSON 与 Markdown 会在返回之前写出，以保留全部测量结果。

| 数据文件 | SHA-256 |
|---|---|
| `npu_gemm` | `7926aa0dc579323fc1c75dc6fc66c94abc87a87508d65abf75e721061f43b7c4` |
| `npu_conv` | `c47b1011b7388ebe17c1724aace7de3d80f3b8a3f8734114eff98a8586bd69a7` |
| `gemmini_gemm` | `1a677b0e7736dfda0f0079e70c78b1f46cde8862d047b96395e92cdea0769ca9` |
| `gemmini_native` | `20e40bf65c6e6a57e775879e7cf0ff221166f66c4a0a733ddaa995894bfe46bb` |
| `gemmini_im2col` | `4a79fe12bc19e065e746c01f6c77cb78c479f07de618ba59acef7ee96de59d44` |
| `gemmini_build` | `0677596789b4419f809fd20ddab8d2667ca00ce7538a6c36f2bacb33cfd1dedc` |
| `npu_gemm_build` | `65eb4d64182f37aa252e31db161b5d2ea5a32098c2a1fda772a5ac551efb7b01` |
| `npu_conv_build` | `c3b0be86d0929ef29818c4402bd009db5dd81aae12dfbcb81469675b17e207c9` |
| `gemmini_generated_rtl` | `d5913f226b1d174be2d386db7374ce839793259eaefb1451aa39ee0e0b94ed99` |
| `gemmini_params_header` | `082a7047a1d66f53b5d0652773027793c92aff06949624b7b93674240afbea56` |
| `shared_comparison_code` | `1a702aedb7236603c028c08f9cfd8dc3bf4b3dd353c391fa74f228ed276fe21a` |

[^npu_gemm]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/npu_gemm/summary.json`，SHA-256 `7926aa0dc579323fc1c75dc6fc66c94abc87a87508d65abf75e721061f43b7c4`。
[^npu_conv]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/npu_conv/summary.json`，SHA-256 `c47b1011b7388ebe17c1724aace7de3d80f3b8a3f8734114eff98a8586bd69a7`。
[^gemmini_gemm]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_gemm_results/results.json`，SHA-256 `1a677b0e7736dfda0f0079e70c78b1f46cde8862d047b96395e92cdea0769ca9`。
[^gemmini_native]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_conv_native/results.json`，SHA-256 `20e40bf65c6e6a57e775879e7cf0ff221166f66c4a0a733ddaa995894bfe46bb`。
[^gemmini_im2col]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_conv_im2col/results.json`，SHA-256 `4a79fe12bc19e065e746c01f6c77cb78c479f07de618ba59acef7ee96de59d44`。
[^gemmini_build]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_build/generated_sp32_acc32_axi64_spdelay1/build_manifest.json`，SHA-256 `0677596789b4419f809fd20ddab8d2667ca00ce7538a6c36f2bacb33cfd1dedc`。
[^npu_gemm_build]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/npu_gemm/sim/build.json`，SHA-256 `65eb4d64182f37aa252e31db161b5d2ea5a32098c2a1fda772a5ac551efb7b01`。
[^npu_conv_build]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/npu_conv/sim/build.json`，SHA-256 `c3b0be86d0929ef29818c4402bd009db5dd81aae12dfbcb81469675b17e207c9`。
[^gemmini_generated_rtl]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_build/generated_sp32_acc32_axi64_spdelay1/GemminiCompare.v`，SHA-256 `d5913f226b1d174be2d386db7374ce839793259eaefb1451aa39ee0e0b94ed99`。
[^gemmini_params_header]: `/workspace/scratch/dc14ec427142/measurements/axi64/sync_latency8/gemmini_build/generated_sp32_acc32_axi64_spdelay1/gemmini_params.h`，SHA-256 `082a7047a1d66f53b5d0652773027793c92aff06949624b7b93674240afbea56`。
[^shared_comparison_code]: `/workspace/scratch/dc14ec427142/mini_tflm_dsa/test/gemmini_comparison/compare_fair_operators.py`，SHA-256 `1a702aedb7236603c028c08f9cfd8dc3bf4b3dd353c391fa74f228ed276fe21a`。
