# 独立量化算术通道

`requant_compute_lane` 在同一个接受边沿保存有符号 INT32 数据、预处理乘数和七位移位量，依次完成完整 INT64 乘积、带溢出检查的移位、最近偶数舍入、输出偏移及激活范围裁剪。乘法使用四个 DSP，舍入与偏移共用一个 DSP。

## 接口与时序

输入到输出共有十二个使能采样边沿：三个乘法阶段、七个移位阶段、一个舍入加法阶段和一个输出阶段。

- `i_en=0` 时，数值、有效位和尾列屏蔽状态共同保持。
- `i_clear=1` 时，清除所有有效位及两个输出，清空优先于使能。
- `rst_n=0` 异步清除有效位和输出；数值流水由有效位管理。
- `i_valid` 表示一次批次输入，`i_lane_enable=0` 使该批次的两个数值输出均为零。
- `i_s16`、`i_dst_offset` 和激活边界在有效流水期间保持。清空或流水排空后可以更新这些配置。
- INT16 模式使用零输出偏移。INT8 和 INT16 输出均保留激活边界优先于目标位宽饱和的顺序。

模块复用 `registered_multiplier_s32`、`requant_shift_pipeline`、`requant_registered_sum` 和 `requant_activation_compare`。左右乘法输入均启用输入寄存器。乘法的完整输入与暂停证明见 [四 DSP 乘法器](../requant_four_dsp/README.md)，移位关系证明见 [量化移位](../requant_shift_clamp/README.md)。

## 数值与周期检查

`main.cpp` 使用独立的 128 位整数参考计算乘积、商、余数及舍入，负数除法显式转换为向下取整。通用 RTL、实际 FPGA 原语和实际综合后的 Verilog 使用同一个参考程序；C++ 编译启用未定义行为检查。

每种实现均通过以下检查：

| 项目 | 数量 |
| --- | ---: |
| 总周期 | 1,057,997 |
| 有效结果 | 838,131 |
| 定向输入 | 524,288 |
| 随机输入 | 524,288 |
| 暂停周期 | 73,578 |
| 清空周期 | 3,129 |
| 复位周期 | 468 |
| 清空与暂停同时发生 | 787 |
| 尾列屏蔽输入 | 42,431 |

定向输入覆盖全部 128 种移位量、两种输出模式、16 个数值边界、16 个乘数边界和八组激活范围/偏移。所有周期检查公开有效位和两个完整输出，包括暂停期间保持和清空期间归零。

## 独立综合

Yosys 0.71、ABC9、Xilinx 7 系列原语下，所有公开输出均参与综合：405 个逻辑 LUT、12 个 SRL LUT、297 个触发器、5 个 DSP、18 个 CARRY4，无块 RAM。完整按位连接图的最长寄存器间组合路径为 9 个单元，位于舍入结果至输出裁剪寄存器。物理面积与完整 SoC 时序通过整机实现统计。

`measurement.json` 保存源文件、原语库、实际综合网表和验证程序的 SHA-256，以及三个实现的检查结果。

## 运行

```sh
python3 test/requant_compute_lane/run.py \
  --out build/requant_compute_lane/numeric --jobs 2

python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/requant_compute_lane/synthesis_cases.json \
  --cases requant_compute_lane --out build/requant_compute_lane/synthesis

python3 test/requant_compute_lane/run.py \
  --out build/requant_compute_lane/mapped_numeric --variants mapped \
  --mapped build/requant_compute_lane/synthesis/requant_compute_lane/mapped.v \
  --jobs 2
```

独立综合使用 `requant_compute_lane` 为顶层，读取该模块以及 `vector_scalar_multiplier.sv`、`vec_requant.sv`，其余参数保持默认值。
