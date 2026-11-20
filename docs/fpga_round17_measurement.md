# 第17轮完整SoC综合与组合路径

固定源码提交为 `2407d9d674cc314b0347df7b510c33cabcac9cb4`，顶层为 `soc_top`，目标器件为 `xc7a200tfbg484-3`。配置保留16×16阵列、8个向量PE、INT8/INT16/INT32、64位总线、4 KiB im2col缓存、7个8 KiB共享银行、16个部分和帧、原始INT32部分和与256 KiB CPU RAM。生产量化使用两个计算通道和512行整组缓存。

完整综合得到 **49,560个逻辑LUT、2,444个RAM LUT和24个SRL**，布局前名义总数为 **52,028**。寄存器之间的最长组合路径为 **20级**。完整数据与源码、工具及映射文件的SHA256保存在 [fpga_round17_measurement.json](data/fpga_round17_measurement.json)。

## 资源

| 资源 | 数量 |
| --- | ---: |
| 逻辑LUT原语 | 49,560 |
| RAM LUT位置 | 2,444 |
| SRL位置 | 24 |
| 布局前名义LUT总数 | 52,028 |
| FF | 42,863 |
| DSP48E1 | 740 |
| RAMB36E1 | 91 |
| RAMB18E1 | 45 |
| CARRY4 | 1,856 |

物理打包已完成36组余因子合并，并建立2,650组普通LUT、1,634组寄存LUT、99组混合LUT和184组进位相关LUT配对约束。配对过程检查功能单元内容保持一致。物理LUT位置数需要使用合法布局后的实际位置计数；当前固定源码尚未完成布局及布线时序测量。

## 组合路径

分析遍历映射后的实际连接图，所有单元均完成分类，图中没有组合环。计数包含DSP内部寄存边界之间的组合运算。导出的200组路径包括10组20级、23组19级、12组18级、50组17级、73组16级和32组15级。

| 起点与终点 | 级数 |
| --- | ---: |
| 前端 `last_p` → `row_wrap_q` | 20 |
| DMA `job_range` → 多模块中止、全局控制及向量状态 | 20 |
| 前端状态 → IA缓存写数据 | 19 |
| 缓存预取项代次 → 活动预取地址及代次 | 18 |
| 缓存填充状态 → 前端请求索引 | 18 |
| IA帧结束条件 → 读取授权 | 17 |
| 缓存快照地址 → 预取及快照有效状态 | 17 |

## 映射验证

DSP预算为740，宽算术候选的最小位宽为8，同一条组合路径最多包含一个被选中的组合DSP。实际结构包含362个原有DSP，另选取378个算术单元。全部100组位宽与符号参数使用官方模型完成所有输入取值的SAT证明，检查 `X`、`Y` 和全部 `CO` 位。ABC9技术映射的网络等价检查通过。

目标时钟周期为6.667 ns。组合级数用于结构优化，150 MHz结果需要目标器件完整延迟模型及实际布线后的时序分析。

## 重现

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --cases soc_top --out build/soc_round17_dsp740_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 1

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_round17_dsp740_pre/soc_top \
  --out build/soc_round17_dsp740_cost/soc_top \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
  --max-lut-inputs 8

python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/soc_round17_dsp740_pre/soc_top/pre_alu.json \
  --selection build/soc_round17_dsp740_pre/soc_top/wide_alu_mapping.json \
  --top soc_top --out build/round17_selected_dsp_formal
```

映射网表SHA256：`08075c4dfb66bd288a2f8b0ce27931b25aafd585768e09811f41173a464ec81c`。
