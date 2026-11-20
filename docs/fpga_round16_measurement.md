# 第16轮完整SoC综合与组合路径

固定源码提交为 `af11d787a50663d62339e36bffc0694340c76734`，顶层为 `soc_top`，目标器件为 `xc7a200tfbg484-3`。配置保留16×16阵列、8个向量PE、INT8/INT16/INT32、64位总线、4 KiB im2col缓存、7个8 KiB共享银行、16个部分和帧、原始INT32部分和与256 KiB CPU RAM。生产量化使用两个计算通道和512行整组缓存。

完整测量为 **50,050个逻辑LUT、2,444个RAM LUT和24个SRL**，布局前名义总数为 **52,518**。寄存器之间的最长组合路径为 **21级**。本报告对应上述固定源码；完整测量数据保存在 [fpga_round16_measurement.json](data/fpga_round16_measurement.json)。

## 资源

| 资源 | 数量 |
| --- | ---: |
| 逻辑LUT原语 | 50,050 |
| RAM LUT位置 | 2,444 |
| SRL位置 | 24 |
| 布局前名义LUT总数 | 52,518 |
| FF | 42,817 |
| DSP48E1 | 740 |
| RAMB36E1 | 91 |
| RAMB18E1 | 45 |
| CARRY4 | 1,861 |

物理LUT合并与布局期间的额外单元以实际布局结果计数。当前固定源码尚未完成物理布局和布线时序测量。

## 组合路径

分析遍历实际映射连接图，所有单元均完成分类，图中没有组合环。计数包含DSP内部实际寄存边界之间的组合运算。导出的200组最长路径包括6组21级、13组20级、27组19级、53组18级、57组17级和44组16级。

| 起点与终点 | 级数 |
| --- | ---: |
| 权重加载器候选字段 → 全局控制及帧调度状态 | 21 |
| 读取描述符地址 → DMA后续拍数 | 20 |
| 帧调度器 `opened` → 命令列数及计算进度 | 19 |
| 前端配置 → tap更新与状态选择 | 18 |
| 向量写回偏移 → DMA写入数据保持寄存器 | 18 |
| 前端返回选择 → IA缓存写数据 | 18 |
| 向量状态 → DMA上下文地址 | 17 |

## 映射验证

DSP预算为740，宽算术候选的最小位宽为8，最多允许一个被选中的组合DSP出现在同一条组合路径。实际结构包含361个原有DSP，另选取379个算术单元。全部102组位宽与符号参数使用官方模型完成所有输入取值的SAT证明，检查 `X`、`Y` 和全部 `CO` 位。ABC9技术映射的网络等价检查通过。

目标时钟周期为6.667 ns。组合级数和映射延迟模型用于结构优化，150 MHz结果需要目标器件完整延迟模型及实际布线后的时序分析。

## 重现

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --cases soc_top --out build/soc_round16_dsp740_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 1

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_round16_dsp740_pre/soc_top \
  --out build/soc_round16_dsp740_cost/soc_top \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
  --max-lut-inputs 8

python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/soc_round16_dsp740_pre/soc_top/pre_alu.json \
  --selection build/soc_round16_dsp740_pre/soc_top/wide_alu_mapping.json \
  --top soc_top --out build/round16_selected_dsp_formal
```

映射网表SHA256：`eb67711bfa6bb06cd04c2f428c54844127d9d380d912e79d04d36f4a2dc786d9`。
