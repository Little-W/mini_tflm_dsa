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

`DSA_NN_ACCEL_ALL` 的值为 31，也是默认运行时选择值。在设备空闲时、算子调用前设置选择值；
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
DW/池化部署与本次 SoC 测试使用标准核心 `PCR_ENGINE=0`，固件对应 `DSA_PCR_ENGINE=0`。

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

编译 `NN/Source/ExtraAccFunctions/riscv_conv_acc.c` 时可用
`-DDSA_NN_CONV_DATAFLOW_MODE=0` 选择 WS（默认），或设为 1 选择 IS。
其他值会报编译错误。IS 需要 `CONV_CAPS` bit 2；缺少相应能力时在 START 前走
合法软件回退，不会部分执行后再次计算。低层 `dsa_conv_s8_config_t.dataflow_mode`
仍可按调用选择模式。公共输入 / 输出布局不随模式改变。

硬件路径不使用 scratch，可接受 NULL scratch；通用 buffer-size 查询仍为可能的
软件回退保留空间，调用方不能仅凭几何就假定设备能力和数值范围必然适用。
真实 CPU 执行的性能方法与结果见
[SoC 性能说明](../../docs/conv_soc_performance.md)。

## NPU 配置

默认 NPU 数据通路支持 INT8、INT16 输入及 TFLM 所需量化接口。PCR 面板引擎通过 `PCR_ENGINE=1` 选择，要求 `SIZE=16`、32 位总线、INT8 输入、零输入偏移、无 bias、per-tensor 量化，以及 16 的整数倍矩阵尺寸和地址跨度。它使用编译期配置的部分和页池；例如：

```bash
make vcs-top PCR_ENGINE=1 SIZE=16 IA_CACHE_BLOCKS=64 PS_FRAME_COUNT=25 \
  GEN_ARGS='--K 32 --N 32 --M 32 --lhs_dtype 1 --no_bias --lhs_zp 0 --rhs_zp 0 --tight_strides --ia_reuse_num 2 --w_reuse_num 2'
```

`PS_POOL_BYTES` 指定页池字节数，默认 179200；`PANEL_MAX_R` 和 `PANEL_MAX_W` 指定面板上限，默认均为 16。FPGA 综合脚本使用环境变量 `GEMPACT_PCR_ENGINE=1` 启用该引擎，`GEMPACT_PS_POOL_BYTES` 指定页池大小。

PCR 面板引擎的 Python 周期接口位于 `veri/pcr_model/`。运行前使用 Verilator 构建相应容量配置：

```bash
python3 veri/pcr_model/build_measured_backend.py --size 16 --cache 64 --ps 25 \
  --mem-words 131072 --ps-sector-codec --ps-pool-bytes 179200 \
  --panel-rows 16 --panel-cols 16 --pcr-ps --reference
```

后端生成在 `veri/pcr_model/backends/`。Python 仿真使用 `run.py --backend <后端目录> --case <输入目录>`；独立 RTL 程序 `rtl_reference` 可对相同输入进行周期比较。
