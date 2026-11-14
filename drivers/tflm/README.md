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

## NPU 配置

默认 NPU 数据通路支持 INT8、INT16 输入及 TFLM 所需量化接口。论文中的 PCR 面板引擎通过 `PAPER_ENGINE=1` 选择，要求 `SIZE=16`、32 位总线、INT8 输入、零输入偏移、无 bias、per-tensor 量化，以及 16 的整数倍矩阵尺寸和地址跨度。它使用编译期配置的部分和页池；例如：

```bash
make vcs-top PAPER_ENGINE=1 SIZE=16 IA_CACHE_BLOCKS=64 PS_FRAME_COUNT=25 \
  GEN_ARGS='--K 32 --N 32 --M 32 --lhs_dtype 1 --no_bias --lhs_zp 0 --rhs_zp 0 --tight_strides --ia_reuse_num 2 --w_reuse_num 2'
```

`PS_POOL_BYTES` 指定页池字节数，默认 179200；`PANEL_MAX_R` 和 `PANEL_MAX_W` 指定面板上限，默认均为 16。FPGA 综合脚本使用环境变量 `GEMPACT_PAPER_ENGINE=1` 启用该引擎，`GEMPACT_PS_POOL_BYTES` 指定页池大小。

论文引擎的 Python 周期接口位于 `veri/paper_model/`。运行前使用 Verilator 构建相应容量配置：

```bash
python3 veri/paper_model/build_measured_backend.py --size 16 --cache 64 --ps 25 \
  --mem-words 131072 --ps-sector-codec --ps-pool-bytes 179200 \
  --panel-rows 16 --panel-cols 16 --pcr-ps --reference
```

后端生成在 `veri/paper_model/backends/`。Python 仿真使用 `run.py --backend <后端目录> --case <输入目录>`；独立 RTL 程序 `rtl_reference` 可对相同输入进行周期比较。
