# 第18轮完整SoC综合与NPU回归

固定源码提交为 `3f78c674e78d488fca57baff1d74e5204b4d6f80`，顶层为 `soc_top`，目标器件为 `xc7a200tfbg484-3`。配置保留16×16阵列、8个向量PE、INT8/INT16/INT32、64位总线、4 KiB im2col缓存、7个8 KiB共享银行、16个部分和帧、原始INT32部分和以及256 KiB CPU RAM。生产量化使用两个计算通道和512行整组缓存。

完整综合得到 **50,013个逻辑LUT、2,444个RAM LUT和24个SRL**，布局前名义总数为 **52,481**。合法布局占用 **49,803个物理LUT位置**，满足50,000的面积目标。寄存器之间的最长组合路径为 **20级**。同一RTL版本的完整NPU回归通过86个任务、216,348项INT32数值检查，合计961,873个任务执行周期。

源码清单、工具及映射文件SHA256、实际路径和验证结果保存在 [fpga_round18_measurement.json](data/fpga_round18_measurement.json)，完整NPU任务结果保存在 [fpga_round18_npu.json](data/fpga_round18_npu.json)。

## 资源

| 资源 | 数量 |
| --- | ---: |
| 逻辑LUT原语 | 50,013 |
| RAM LUT位置 | 2,444 |
| SRL位置 | 24 |
| 布局前名义LUT总数 | 52,481 |
| 合法布局后的物理LUT位置 | 49,803 |
| FF | 42,845 |
| DSP48E1 | 740 |
| RAMB36E1 | 91 |
| RAMB18E1 | 45 |
| CARRY4 | 1,862 |

物理位置包含逻辑LUT、RAM LUT和SRL，并按实际BEL所在位置去重统计。全部单元已放置，资源与位置检查通过。实现采用种子1、两次HeAP分析布局及一次退火细化，工具保存较好的合法位置后执行全部位置检查。布线及150 MHz时序验证尚未完成，完整实现结果见 [fpga_round18_placement.json](data/fpga_round18_placement.json)。

## 组合路径

分析遍历映射后的实际连接图，全部单元均已分类，图中没有组合环。计数包含DSP内部寄存边界之间的组合运算。导出的200组路径包含2组20级、9组18级、11组17级、37组16级、54组15级和87组14级。

| 起点与终点 | 级数 |
| --- | ---: |
| DMA上下文计数 → 帧调度器就绪及阶段 | 20 |
| FIFO当前银行 → 银行计数 | 18 |
| DMA上下文计数 → 向量状态及帧调度控制 | 18 |
| 缓存前台状态 → 前端请求索引 | 17 |
| 缓存前台状态 → 前端坐标及分组范围 | 16 |
| DMA读地址 → 响应行地址及下一次突发长度 | 16 |
| 前端状态 → IA缓存写数据 | 16 |

## 功能验证

仿真启用 `XILINX_FPGA` 与 `SYNTHESIS`，使用官方LUT及DSP模型，使用生产版本的两个量化计算通道。各测试共享同一个已核对SHA256的仿真程序，综合与仿真的共同RTL文件逐项核对一致。

| 测试类别 | 任务数 | INT32检查数 | 任务执行周期 |
| --- | ---: | ---: | ---: |
| NPU功能 | 38 | 11,118 | 143,037 |
| 共享银行及部分和容量 | 21 | 173,642 | 663,521 |
| 输出模式 | 15 | 11,392 | 45,446 |
| 紧凑输入格式 | 12 | 20,196 | 109,869 |
| 合计 | 86 | 216,348 | 961,873 |

量化整组缓存实际处理742组、17,360行，覆盖512行最大组以及取消尚未产生数据的保留组。待处理配置累计保持163,340个周期，输入、发出与输出行数一致。

## 技术映射验证

DSP预算为740，宽算术候选最小位宽为8，同一条组合路径最多包含一个选中的组合DSP。实际结构包含362个原有DSP，另选取378个算术单元。所选算术单元对应的全部65组位宽及符号参数均通过官方模型的全输入SAT证明，检查 `X`、`Y` 与全部 `CO` 位。ABC9网络等价检查通过。

目标时钟周期为6.667 ns。组合级数用于结构优化；150 MHz运行频率需要目标器件完整延迟模型和实际布线后的时序分析。

## 重现

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --cases soc_top --out build/soc_round18_dsp740_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 1

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_round18_dsp740_pre/soc_top \
  --out build/soc_round18_dsp740_cost/soc_top \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
  --max-lut-inputs 8

python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/soc_round18_dsp740_pre/soc_top/pre_alu.json \
  --selection build/soc_round18_dsp740_pre/soc_top/wide_alu_mapping.json \
  --top soc_top --out build/round18_selected_dsp_formal
```

映射网表SHA256：`7d60109a7d91331e51529b236d0fcfefc1079cac0de056ed07e206e76c3d27ab`。

仿真程序SHA256：`224596b54fa5804e0189d8b60664c4dd7a62b1b4a4cec8f76a47d89c7aba874b`。
