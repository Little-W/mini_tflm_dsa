# 软件与模型

## 驱动

`drivers/dsa_accel.c` 和 `drivers/dsa_accel.h` 提供 NPU 配置接口，寄存器定义见 [寄存器说明](../drivers/registers_v2.md)。`drivers/gempact_tiling.h` 提供工作组参数的计算函数，软件将计算结果写入相应寄存器。

## TFLM 与 NMSIS

部署模型位于 `drivers/tflm/models/`，模型列表由 `registry.json` 管理。`make model-list` 列出模型；`make model-select MODEL=<名称>` 修改当前选择；`make model-build` 构建固件；`make vcs-tflm` 在 SoC 中运行选定模型。模型对应的存储容量由选择配置提供。

修改后的 NMSIS 位于 `drivers/tflm/NMSIS/`，TFLM 内通过相对符号链接引用模型和依赖。目录结构与更多配置见 [TFLM 说明](../drivers/tflm/README.md)。
