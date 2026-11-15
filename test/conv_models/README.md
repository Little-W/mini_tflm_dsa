# 真实模型尺寸与现场生成的卷积向量

本目录从仓库原有的四个 TFLite 文件提取普通 INT8 `CONV_2D` 元数据，
再用固定种子生成测试张量和独立 C 参考输出。运行不读取已保存的模型目录、
旧测试结果或二进制向量；所有生成物写入 `build/` 或显式 `--out`。
补丁保留脚本、C oracle 和说明，不附生成的 JSON、MEM、BIN、日志或可执行文件。

模型提供完整层尺寸、步幅、dilation 和四边 padding。数值测试使用确定性合成
输入、权重和量化参数，**不是原模型训练权重或整网准确率测试**。
独立参考为 [`reference_conv.c`](../conv_npu/reference_conv.c) 的直接卷积和
仓库实际 NMSIS `riscv_nn_requantize`；不是从待测 RTL 输出反推 golden。

## 生成与核验

需要 Python 3、NumPy、`flatbuffers`、原生 GCC/G++。提取使用仓库自带的
`schema_py_generated.py`，不需要 TensorFlow，也不下载额外模型。

```sh
python3 -m pip install numpy flatbuffers==25.2.10

# 一次生成推荐 10 层：模型元数据、实际 C planner、张量、参考输出和 NPU 描述符。
python3 test/conv_models/generate_vectors.py --out build/conv_models/vectors

# 只生成一个原始层；原 ID 和文件名安全的 slug 均可。
python3 test/conv_models/generate_vectors.py --out /tmp/conv_vectors \
  --layers justure_detect:sg0:op7

# 仅几何/调度分析：不生成任何 MEM/BIN，不表示数值或 RTL 通过。
python3 test/conv_models/generate_vectors.py --out build/conv_models/metadata \
  --metadata-only

# 单独检查模型参数或生产驱动分组；默认直接重新提取 TFLite。
python3 test/conv_models/extract_shapes.py --out build/conv_models/models.json
python3 test/conv_models/verify_metadata.py --out build/conv_models/metadata_validation.json
python3 test/conv_models/driver_tiling_oracle.py --out build/conv_models/driver_tiling.json

python3 -m unittest discover -s test/conv_models -p test_vectors.py -v
```

`make conv-vectors` 调用同一生成器。两个独立核验脚本接受可选 `--models`
指向刚生成的目录 JSON；省略时会重新读取原 TFLite，不依赖固定结果文件。

## 模型来源与层选择

提取脚本固定模型文件 SHA-256，文件变化会导致失败。按实际 FlatBuffer opcode
分类，而非按 tensor 名字猜测。`person_detect` 首层名字含 `Conv2d_0`，实际为
与普通 Conv 不同的 depthwise，因此没有计入普通 Conv；该模型的 14 个普通 Conv 都是 1×1。

| 模型 ID | 仓库原有文件 | 普通 INT8 Conv | 排除的 depthwise |
|---|---|---:|---:|
| `mnist_cnn` | [mnist_cnn_int8.tflite](../../drivers/tflm/models/mnist_cnn/mnist_cnn_int8.tflite) | 2 | 0 |
| `person_detect` | [person_detect.tflite](../../drivers/tflm/models/person_detection_reference/models/person_detect.tflite) | 14 | 14 |
| `justure_detect` | [justure_detect.tflite](../../drivers/tflm/models/my_model/models/justure_detect.tflite) | 12 | 4 |
| `mobilenet_v2` | [mobilenet_v2_quantized_1x3x224x224.tflite](../../drivers/tflm/tflm/tflite-micro/third_party/xtensa/examples/pytorch_to_tflite/mobilenet_v2_quantized_1x3x224x224.tflite) | 35 | 17 |
| 合计 | 4 个模型 | 63 | 35 |

推荐 10 层均来自 subgraph 0，batch=1、groups=1、dilation=1。空间与通道数不缩小：

| 模型 / op | 输入 H×W×C | OHWI 权重 | stride | 输出 H×W×C |
|---|---|---|---:|---|
| MNIST / 0 | 28×28×1 | 8×3×3×1 | 1 | 28×28×8 |
| MNIST / 2 | 14×14×8 | 16×3×3×8 | 1 | 14×14×16 |
| Gesture / 1 | 64×64×1 | 8×3×3×1 | 2 | 32×32×8 |
| Gesture / 7 | 16×16×16 | 32×3×3×16 | 2 | 8×8×32 |
| Gesture / 16 | 8×8×32 | 64×3×3×32 | 2 | 4×4×64 |
| Gesture / 10 | 8×8×64 | 32×1×1×64 | 1 | 8×8×32 |
| Person / 6 | 24×24×32 | 32×1×1×32 | 1 | 24×24×32 |
| Person / 10 | 12×12×64 | 64×1×1×64 | 1 | 12×12×64 |
| MobileNetV2 / 32 | 14×14×192 | 64×1×1×192 | 1 | 14×14×64 |
| MobileNetV2 / 52 | 14×14×96 | 576×1×1×96 | 1 | 14×14×576 |

MNIST 两层四边 padding 为 `1/1/1/1`；Gesture 三个 stride-2 空间卷积为
`top/left/bottom/right=0/0/1/1`，保留模型明确的输出尺寸。其余推荐层四边为 0。
MobileNetV2 op52 的输出为 112896 B，Cout=576 保持原值。

本 NPU 测试 arena 为输入/权重各 64 KiB、每组参数 4 KiB，以及从 `0x40003`
开始的剩余输出空间。63 层中 39 层满足这些测试内存约束；这不表示对任意输入
或任意硬件配置都已验证。选择额外层时，生成器检查 geometry、模型 SHA 和区域边界。

## 稳定数值与分组合同

每层使用独立的 `random.Random(seed)`，缺省种子 `20261115`。选取层的顺序或
只生成子集不会改变相同层的数据。输入和权重为有符号 8 bit，bias/multiplier/shift
为确定性合成参数；input/output offset 为 −7/−3，activation 为 [−117,109]。
生成的模型目录另保留原模型 scale、zero point、量化维度及派生 multiplier/shift，
但数值测试不会暗中把它们当成合成参数。

`verify_metadata.py` 编译仓库实际的 `quantization_util.cc`、`kernel_util.cc`
并调用 `ComputePaddingHeightWidth`，核对 63 层的 11986 个通道量化参数、
63 组 activation 范围和 63 组几何。这是元数据核验，不能算作硬件输出数。

默认 `--tiling-policy driver-auto` 调用真实 `drivers/gempact_tiling.h` C planner：
SIZE16、IA 4 slots、PS 16 frames、WS、per-channel、requested R/W=0/0。
`stress-w2` 显式请求 R/W=2/2，仅作为压力配置。两者只改变 NPU config 的
6、7、30、31 号词，输入、权重、量化和 golden 不变。

| 层 | 自动 R/W | 自动输出通道组 | 固定 2/2 的输出通道组 |
|---|---|---:|---:|
| Gesture op16 | 1/4 | 1 | 2 |
| Person op10 | 2/4 | 1 | 2 |
| MobileNetV2 op32 | 2/4 | 1 | 2 |
| MobileNetV2 op52 | 2/16 | 3 | 18 |

其他推荐层的六个规划字段完全相同。C planner 证明分组参数；性能必须由对应
真实 RTL/SoC runner 执行后记录，不能用调度推导代替实际测量。

## Python 公共接口与输出

```python
from pathlib import Path
from generate_vectors import generate_layers

generated = generate_layers(
    Path("build/conv_vectors"),
    selected=["justure_detect:sg0:op7"],
    seed=20261115,
    tiling_policy="driver-auto",
    metadata_only=False,
)
case_path = generated["cases"]["justure_detect_sg0_op7"]
layer = generated["layers"][0]
```

从其他测试目录导入时，将 `test/conv_models` 加入 Python module 搜索路径。
可选 `ref` 传入已有 `conv_npu.run.make_reference()` 返回值，避免重复编译参考库。
返回的 `layers` 包含 `layer_id`、`layer_slug`、`model_layer`、`parameters`、
`tiling` 和 `tensors`。`cases` / `bypass_cases` 按安全 slug 索引生成目录。
`metadata_only=True` 时 `cases` 为空、输出 SHA 为 `None`，明确无数值结果。

正常生成目录含 `models.json`、生成器源摘要和 `manifest.json`；每层目录含
六份 tensor BIN、`init.mem`、`golden.mem`、`required.mem`、`config.mem` 和
`case.json`。旁路只改变 bypass config 词并复用相同内存/golden。源模型、
参考函数、planner 和生成器均记录 SHA，所有输出可重建且不应提交到 Git。

`test_vectors.py` 检查子集/完整生成的一致性、seed 的作用、metadata-only 无
数值 payload，以及仓库外 SoC 内存映像的相对来源路径。
