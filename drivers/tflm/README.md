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

## 普通 s8 Conv 的硬件 im2col

标准 s8 generic、wrapper、1×1、fast 1×1、1×N 和对应 `_acc` 入口会在 CPU
im2col / scratch 检查之前尝试原图 Conv。受支持任务直接提交 NHWC 输入和 OHWI
权重；共享 block_dma 生成已加 input_offset 的 s16 矩阵块，loader 无需辨别其
来自外部矩阵还是卷积窗口。完整接口与约束见
[DMA 设计说明](../../docs/block_dma_im2col.md)。

`DSA_NN_CONV_ENABLE` 默认为 1；设为 0 会使用普通 NMSIS 软件回退，它不等于
本仓库历史上的“CPU im2col 加 DSA GEMM”性能基线。后者已作为精确源快照保留在
SoC 性能测试中，避免混淆两种软件路径。

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
