# IA 紧凑存储的真实 GEMM 测试

`IA_COMPACT_ENABLE` 默认值为 `0`。该参数可在工程配置或顶层参数中显式设为 `1`。
配置值沿 FPGA、SoC、AXI-Lite 和 NPU 包装层传入 IA 装载模块，并参与容量计算和构建缓存标识。
AXI-Lite 的 `PS_CAPS[2]` 表示编译后的 IA 紧凑存储能力。

## 存储结构

IA 与 PS 使用同一组多 bank SRAM。这里的配置为 7 个 8 KiB bank，总容量为 56 KiB。
普通格式分配 2 个 bank 给 IA；紧凑格式可以分配 1 个或 2 个 bank，其余容量用于 PS。
自动分配时，普通格式使用 2 个 bank，紧凑格式使用 1 个 bank。IA 装载模块只提供共享 SRAM 端口，
模块内保存槽位、行列有效范围和读取流水线状态。`im2col` 输入缓存容量为 4 KiB。

对于原始有符号 INT8 数值 `x`，装载的数据为 `y = x + compact_offset`。
紧凑存储写入 `y - compact_offset` 的 8 位值，读取时符号扩展并加回 `compact_offset`。
适用条件是源数据为 INT8、内部数据宽度为 16 位，且 `compact_offset` 位于 `[-127, 128]`；
该偏移范围也保证填充值能够编码。每个适用元素占用 1 字节，普通格式占用 2 字节。
这些条件直接来自数据格式和偏移量，组内元素跨度不参与压缩条件判断。

关闭编译开关时，综合裁剪紧凑格式转换、还原加法及对应寄存器。
开启时，共享 SRAM 输出先进入数据寄存器，再完成符号扩展与偏移还原。

## 输入与参考结果

测试使用完整算子形状、训练所得权重和图像推理产生的真实激活值：

| 模型 | 输入来源 | 完整 GEMM 形状 `M × K × N` | 实测 GEMM 数 |
| --- | --- | --- | ---: |
| MobileNetV1 VWW | 两个已记录的图像推理样本 | `576 × 16 × 32`、`144 × 64 × 64`、`9 × 128 × 256` | 6 |
| ResNet8 CIFAR-10 | 两个已记录的图像推理样本 | `1024 × 144 × 16`、`64 × 576 × 64` | 4 |
| MobileNetV2 | 模型附带的量化图像，经 LiteRT 参考内核运行 | `196 × 192 × 64`、`196 × 96 × 576` | 2 |

前两种模型的记录来自 `npu_gemmini_measurements_20261121.tar.xz`。
MobileNetV2 使用仓库内 `drivers/tflm/tflm/tflite-micro/third_party/xtensa/examples/pytorch_to_tflite/`
目录中的 `mobilenet_v2_quantized_1x3x224x224.tflite` 和 `pytorch_images_dog_jpg.cc`。
`prepare.py` 校验模型、输入和张量的 SHA-256，再将卷积展开为 GEMM。

数值参考使用 NumPy INT64 矩阵乘法、INT32 范围检查及 Q31 最近偶数舍入。
MobileNetV1 和 ResNet8 同时检查已记录的算子输出。
MobileNetV2 的硬件结果与独立 GEMM 数学参考比较。
每次 RTL 运行检查全部 INT32 累加结果、最终 INT8 输出及完整 512 KiB 外部存储空间。
本测试的性能范围为选定 GEMM，周期统计从任务开始被接收到完成有效，不包含完成接收暂停时间。

对这些模型的 85 份普通卷积或全连接算子输入进行了格式统计：
共 4,504,480 个展开后元素，全部满足紧凑格式条件，全部逐元素还原正确。
有效数据容量由 9,008,960 字节减少为 4,504,480 字节。

## 测量配置与结果

两种编译配置均使用 16 × 16 阵列、16 个向量处理单元、64 位 AXI、
4 KiB `im2col` 输入缓存、128 字节缓存行和 56 KiB 共享 SRAM。
PS 保存原始 INT32 数据。AXI 存储模型首响应延迟为 8 周期，连续响应间隔为 1 周期。
两个配置通过同一份生产软件调度器生成任务参数。

运行组合为：

1. `off_auto`：关闭 IA 紧凑存储，按实际容量自动调度。
2. `on_fixed`：开启 IA 紧凑存储，复用 `off_auto` 的任务分块参数。
3. `on_auto`：开启 IA 紧凑存储，按实际容量重新自动调度。

本组输入中，两个开启组合的 `R`、`W`、数据流及执行周期相同。
`on_auto` 将 IA 分配从 2 个 bank 减少为 1 个 bank，PS 可用容量相应增加 8 KiB。

| 模型 | 关闭时周期 | 开启时周期 | 开启后的周期变化 | 关闭时读取字节 | 开启时读取字节 |
| --- | ---: | ---: | ---: | ---: | ---: |
| MobileNetV1 VWW | 58,746 | 58,810 | +0.1089% | 134,656 | 134,656 |
| ResNet8 CIFAR-10 | 131,046 | 131,176 | +0.0992% | 462,720 | 462,720 |
| MobileNetV2 | 134,754 | 134,616 | −0.1024% | 357,248 | 354,944 |
| 合计 | 324,546 | 324,602 | +0.0173% | 954,624 | 952,320 |

36 次 RTL 运行全部通过，共检查 678,912 个 INT32 累加结果及对应量化输出。
在相同的物理容量下，紧凑存储使总读取量减少 2,304 字节，约为 0.2414%，总周期增加 56。

IA 共享存储接口的 XC7 映射估计如下。测量包含地址、掩码、元数据和格式转换逻辑；
外部共享 SRAM 数据阵列不计入该表。元数据均推断为 1 个 RAMB18，DSP 数量为 0。

| DMA 通道数 | 开关 | LUT | FF | 最长寄存器间组合单元数 |
| ---: | ---: | ---: | ---: | ---: |
| 8 | 0 | 1,162 | 201 | 7 |
| 8 | 1 | 1,870 | 515 | 7 |
| 16 | 0 | 1,436 | 337 | 7 |
| 16 | 1 | 2,356 | 651 | 7 |

开启功能增加 708～920 个 LUT 和 314 个 FF。结合本组 GEMM 的测量结果，默认关闭该功能。
映射单元数用于检查组合结构；150 MHz 的最终时序结论需要目标器件的布局布线报告。

## 运行方法

准备 Python 依赖 `numpy`、`flatbuffers`、`ai-edge-litert`，并使 Verilator、C++ 编译器可用。
本次测量使用 `flatbuffers 25.2.10` 和 `ai-edge-litert 2.4.0`。
Verilator 的运行版本与模拟程序 SHA-256 保存在 `results.json` 的构建记录中。
已记录输入按 `<模型>/<四位样本编号>/trace/` 放在同一个目录中，目录内包含
`case.json`、`model_after.bin`、`input_after.bin` 和 `tensors/`。

```bash
python3 test/ia_compact_benchmark/prepare.py \
  --captures /path/to/captured_models \
  --out build/ia_compact_benchmark/corpus

python3 test/ia_compact_benchmark/run.py \
  --corpus build/ia_compact_benchmark/corpus \
  --out build/ia_compact_benchmark/results \
  --builds build/ia_compact_benchmark \
  --build --jobs 2

python3 test/ia_compact_benchmark/check_capabilities.py \
  --out build/ia_compact_benchmark/capabilities
```

`results.json` 保存各算子的周期、访存量、调度参数、构建输入摘要及容量检查结果。
执行程序与源文件均以 SHA-256 检查，构建过程中输入发生变化时测试会终止。
