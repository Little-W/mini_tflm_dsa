# TFLM 模型与 NMSIS

部署模型集中存放于 `models/`。`models/registry.json` 列出可选择的应用、模型目录与固件构建目标。模型数据、生成的 C/C++ 数组及其测试数据放在对应模型目录中。`person_detection_reference/` 保存人员检测模型的另一组输入与示例源码。

在仓库根目录执行：

```bash
make model-list
make model-select MODEL=mnist_mlp_int16x8
make model-build
make vcs-tflm
```

不指定 `MODEL` 时，`make model-select` 显示编号菜单。也可以运行 `python3 drivers/tflm/select_model.py --list` 或 `--select <名称>`。选择结果保存在 `model_selection.mk`；`model-build` 和 `vcs-tflm` 使用该配置及模型对应的 SoC 存储深度。命令行的 `TFLM_APP` 可单次覆盖仿真应用。

NMSIS 源码位于 `NMSIS/`，加速器接口位于 `NMSIS/NN/Source/ExtraAccFunctions/` 和 `NMSIS/NN/Include/`。TFLM 内原有的模型和依赖引用使用相对符号链接，构建产物位于构建目录。

完整网络运行与周期比较见 [完整模型测试](../../test/model_benchmark/README.md)。
VCE 的能力、量化规则、DMA 访问和寄存器接口见
[VCE 设计与驱动](../../docs/vector_engine.md)。运行时选择和 TFLM 适配范围如下。

## s8 硬件调用与软件选择

本节的数值规则和模型检查对应 RV32IM 标量软件及当前标准核心硬件配置。

`USE_NMSIS_NN=1` 时，TFLM 使用 NMSIS 的 Conv、DW、全连接和池化适配函数。
倍率 1 的 DW 与平均/最大池化调用共享 DMA 的 `vector_engine`；单输入通道、
倍率 2 至 16、窗口不超过 49 个位置的 s8 DW 可将权重转换为 OHWI，使用普通 Conv
计算单元。普通 Conv 和全连接使用矩阵计算路径。
TFLM 通用 Add 内核中的无广播 INT8 运算可以调用 VCE；其软件路径继续使用
TFLM 通用 Add。适配函数将 NMSIS 返回的错误传递给 `MicroInterpreter::Invoke()`。
适配函数保存一次 NMSIS 调用的返回值，DW 与池化参数保留张量中的实际 batch 数量。

编译设置 `DSA_NN_RUNTIME_CONTROL=1` 后，同一固件可以通过
`riscv_nn_dsa.h` 中的接口选择 s8 运算的执行方式：

```c
dsa_nn_set_accelerators(0);                  /* NMSIS 软件运算 */
dsa_nn_set_accelerators(DSA_NN_ACCEL_CONV |
                        DSA_NN_ACCEL_FC);    /* Conv 与全连接使用硬件 */
dsa_nn_set_accelerators(DSA_NN_ACCEL_ALL);    /* 启用全部 s8 硬件路径 */
```

| 位 | 常量 | s8 运算 |
|---:|---|---|
| 0 | `DSA_NN_ACCEL_CONV` | 普通 Conv |
| 1 | `DSA_NN_ACCEL_DW` | Depthwise Conv |
| 2 | `DSA_NN_ACCEL_POOL` | 平均池化、最大池化 |
| 3 | `DSA_NN_ACCEL_FC` | 全连接 |
| 4 | `DSA_NN_ACCEL_ADD` | 无广播 INT8 Add |
| 5 | `DSA_NN_ACCEL_SOFTMAX` | INT8 Softmax |

`DSA_NN_ACCEL_ALL` 的值为 63，也是默认运行时选择值。在设备空闲时、算子调用前设置选择值；
选择软件运算的路径不访问 NPU MMIO。`DSA_NN_CONV_ENABLE`、
`DSA_NN_VECTOR_ENABLE` 和 `DSA_NN_FC_ENABLE` 分别控制编译期支持，均默认为 1。
运行时选择受编译期设置限制。三个编译开关同时作用于 C 和 C++。
未启用运行时选择时，保持编译期决定的行为。
`riscv_dw_pool_acc.h` 提供兼容头；仅指定 `DSA_NN_DW_POOL_ENABLE` 时，该值仍可
控制 VCE 的编译开关。

VCE Add 接受两个等长 INT8 向量，两个输入分别使用自己的 offset、Q31 multiplier
和 shift，再对和执行输出量化。输入 offset 为 `[-127,128]`，输出 offset 为
`[-128,127]`，共同左移量为 `[0,22]`，输入 shift 为 `[-31,0]`，输出 shift 为
`[-31,30]`，三个 multiplier 均为非负 INT32。三次缩放分别执行最近偶数舍入。

硬件 Add 输出必须与两个输入区间分离。NMSIS 允许软件原位计算，但输出与每个输入
之间必须完全同址或互不相交；任意部分相交均返回参数错误。两个只读输入可彼此重叠。
广播 Add 使用 TFLM 通用软件实现。

DW 核面积上限为 49，池化窗口上限为 256，支持 25×5、8×8 和 16×16 窗口。
驱动读取 `CAPS[4]` 和 `NPU_REG_POOL_MAX_TAPS` 检查实际池化容量；设备未声明
独立池化容量时使用能力寄存器中公布的窗口上限。合法窗口超出硬件能力时执行软件路径。
平均池化按有效输入元素求和，padding 不参与计数，最终平均值使用最近偶数舍入。

INT8 Conv、DW 和 FC 的重新量化保留完整 Q31 乘积，计算
`RNE(accumulator * multiplier / 2^(31-shift))`，再处理输出 offset 和激活裁剪。
软件 INT32 饱和以及安全 offset 加法保证极值输入的行为有定义。
TFLM Softmax 的定点乘法、除法和最终输出缩放同样采用最近偶数舍入。

全连接的 s8 `_acc` 入口在启动前检查设备、地址范围、参数和保守数值范围。
不支持的配置使用 NMSIS 软件函数；设备忙或已启动任务发生错误时返回错误。
TFLM 将全连接输出的前导维度展平为 batch，rank 2、3、4 均通过 FC 入口执行，
保留输入、权重、输出的量化偏移，并由 `DSA_NN_ACCEL_FC` 控制硬件选择。
标准 buffer-size 查询为可能使用的软件路径保留空间，运行时切换无需重新分配张量。

单输入通道 DW 的选择仍由 `DSA_NN_ACCEL_DW` 控制，并要求设备同时支持 DW s8
和 Conv s8/narrow-read。普通 Conv 的选择位单独不启用 DW 映射。
DW wrapper、`_acc` 和 `_dsp` buffer-size 查询返回软件空间与权重转换空间的较大值；
转换需要 `Kh*Kw*Cout` 字节，最多 784 字节，与运行选择值无关。
TFLM `Prepare()` 保存分配大小，调用驱动时传入 `ctx.buf` 和真实 `ctx.size`。
驱动在转换前检查空间、内存重叠、能力与量化范围，转换一次后由全部 batch 共用；
每个 batch 提交一次 Conv，执行错误立即返回。
这些自动分派用于 s8 算子，其他合法 DW 配置继续使用 NMSIS 软件实现。
DW 和池化使用统一 NPU 中的 VCE，可与 `PCR_ENGINE=1` 的 PS 压缩配置共同使用。

运行驱动与 TFLM 适配检查：

```bash
python3 test/nmsis_runtime/run.py --out build/nmsis_runtime
python3 test/vector_engine_driver/run.py --out build/vector_engine_driver
python3 test/vector_engine_driver/run_tflm_add.py --out build/tflm_add_selection
python3 test/software_rne/run.py --out build/software_rne --prepared /path/to/prepared
```

测试遍历 32 种运行时选择组合，核对软件输出、MMIO 请求、batch 参数和错误返回。
FC 适配测试调用实际 `Prepare`、`EvalInt8`，覆盖三种 rank、两种量化方式、
可选偏置、scratch/persistent 缓冲区以及单次调用的错误返回。
DW 适配测试覆盖倍率 2、3、8、16、batch 1/2、两种量化元数据、scratch 指针和大小。
DW 驱动测试检查权重转换、32 种运行选择、软件输出、缓冲区不足与重叠，以及首个和后续 batch 的错误处理。
Add 检查覆盖硬件选择、广播、原位输出、部分覆盖、量化参数边界和设备错误。
独立整数参考检查与真实 Add、Softmax 张量比较启用 UBSan。

## 普通 s8 Conv 的硬件 im2col

标准 s8 generic、wrapper、1×1、fast 1×1、1×N 和对应 `_acc` 入口会在 CPU
im2col / scratch 检查之前尝试原图 Conv。受支持任务直接提交 NHWC 输入和 OHWI
权重；共享 block_dma 生成已加 input_offset 的 s16 矩阵块，loader 无需辨别其
来自外部矩阵还是卷积窗口。完整接口与约束见
[DMA 设计说明](../../docs/block_dma_im2col.md)。

`DSA_NN_CONV_ENABLE` 默认为 1；设为 0 会使用普通 NMSIS 软件实现。
Conv 的 SoC 性能测试另外提供 CPU im2col 与 DSA GEMM 组合实现，
分别统计两种执行方式的周期。

`DSA_NN_CONV_DATAFLOW_MODE` 支持 0（WS）、1（IS）和 2（AUTO），默认值为 2。
AUTO 根据设备能力、张量形状和共享存储容量选择 WS/IS、R/W 及 IA bank 数。
强制 IS 需要 `CONV_CAPS` bit 2；缺少相应能力时在 START 前执行软件路径。
低层 `dsa_conv_s8_config_t.dataflow_mode` 可按调用选择模式，公共输入和输出布局
在各模式下保持相同。

硬件路径不使用 scratch，可接受 NULL scratch；通用 buffer-size 查询仍为可能的
软件回退保留空间，调用方不能仅凭几何就假定设备能力和数值范围必然适用。
真实 CPU 执行的性能方法与结果见
[SoC 性能说明](../../docs/conv_soc_performance.md)。

## NPU 配置

默认路径支持 INT8、INT16 输入、硬件 Conv、WS/IS 和 TFLM 所需的逐通道量化。`PCR_ENGINE=1` 在统一路径内启用无损 PS 压缩与容量调度；默认使用七个 2 KiB 的 IA/PS 共享 bank。

```bash
make vcs-top PCR_ENGINE=1 SIZE=16 IA_CACHE_BLOCKS=4 PS_FRAME_COUNT=16 \
  PS_POOL_BYTES=12288 GEN_ARGS='--K 32 --N 64 --M 32 --tight_strides'
```

软件通过能力寄存器查询可用容量，在 Prepare 阶段选择每层的 IA bank 数、R/W、WS/IS 和 PS 策略，并保存到任务描述符。Invoke 提交准备好的寄存器配置。比较运行时 RAW32 与压缩时，在 AllocateTensors/Prepare 前调用 `dsa_set_ps_force_raw(1)` 或 `dsa_set_ps_force_raw(0)`。

### Prepare 中的 arena 配置

`MicroInterpreter::AllocateTensors()` 调用各算子的 `Prepare()`。
公共函数 `nmsis_nn::InitializeLayerConfig()` 通过 `AllocatePersistentBuffer()`
为每层分配配置对象，再调用相应的驱动准备函数。算子的 `OpData` 保存该对象的
指针；配置对象在 interpreter 的整个生命周期内使用 persistent arena 存储。
同一算子再次执行 `Prepare()` 时，会复用配置对象的地址并重新初始化其内容。

| 算子 | arena 中的配置类型 | NMSIS 执行入口 |
|---|---|---|
| Conv、Dense、Depthwise、Pool | `dsa_prepared_t` | `riscv_nn_execute_prepared_s8()` |
| Add | `dsa_prepared_add_s8_t` | `riscv_nn_execute_prepared_add_s8()` |
| Softmax | `nmsis_nn_prepared_softmax_s8_t` | `riscv_nn_execute_prepared_softmax_s8()` |

矩阵配置的准备过程完成形状、数据格式和地址范围检查，读取设备能力，计算静态
权重的部分和范围，选择 IA/PS 分配、R/W、WS/IS 和 PS 策略，并保存固定寄存器
序列。需要排列的权重在这一阶段写入 persistent arena。`source_filter_base`
保留原始模型权重地址，`readonly` 区间记录执行时使用的权重、偏置和量化数组。
Softmax 的查找表也保存在 persistent arena 中。

已经成功准备且运行时启用硬件的算子，在 `Invoke()` 中向 NMSIS 传入只读配置
指针和当前输入、输出地址。该执行入口使用保存的参数提交任务，不重新选择分块、
排列权重或分配配置空间。驱动检查本次输入、输出范围及它们与只读常量的关系，
并把执行状态返回给 TFLM。配置对象中的 `ps_control` 和 `ia_bank_count` 保持
Prepare 选定的容量策略。

配置存储分配失败时，`Prepare()` 返回 `kTfLiteError`。合法配置不满足硬件能力
时，准备函数保持描述符无效，由现有软件实现计算。硬件任务已经提交后发生的
执行错误会返回给调用者。

在 `AllocateTensors()` 或 `Prepare()` 之前设置 `dsa_set_ps_force_raw()`，使该层
按选定策略准备配置。模型形状、权重、量化参数或设备容量发生变化时，应重新
准备受影响的配置。重复执行时，配置及其常量保持只读，输入和输出地址由当前
张量提供。

### 配置复用的验证

[连续 Invoke 测试](../../test/prepared_lifecycle/README.md) 对四个模型、两个输入和
RAW32/adaptive 两种策略分别创建 interpreter，每个 interpreter 只调用一次
`AllocateTensors()`，随后连续调用三次 `Invoke()`，共 16 个仿真进程和 48 次完整
推理。测试比较每次输出的全部字节，并检查规划计时、Prepare 次数、arena 使用量、
配置地址、配置内容和只读权重在执行期间保持不变。

主机测试覆盖两套驱动、重复 Prepare、配置分配失败、运行时选择、软件回退和设备
错误返回：

```bash
python3 test/prepared_dispatch/run.py --out build/prepared_dispatch
python3 test/vector_engine_driver/run_tflm_add_prepared.py --out build/tflm_add_prepared
python3 test/vector_softmax/run_tflm.py --out build/tflm_softmax_prepared
```

Python 周期接口使用统一 RTL 后端：

```bash
python3 veri/pcr_model/build_measured_backend.py --size 16 --cache 4 --ps 16 \
  --mem-words 131072 --ps-pool-bytes 12288 --reference
```

输出默认位于 `build/pcr_model/`。`veri/pcr_model` 提供兼容入口，实际构建和运行复用 `veri/python_model`。共享 RAM、寄存器及容量统计见 [硬件架构](../../docs/architecture.md)、[寄存器说明](../registers_v2.md) 和 [容量说明](../../docs/capacity.md)。
