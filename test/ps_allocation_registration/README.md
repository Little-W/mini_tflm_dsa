# 共享银行分配结果寄存

`npu_top` 在原有 `cfg_start_event` 边沿同时保存 IA 银行数量、部分和银行数量和分配合法性。三个结果采用同一输入配置和复位条件，后续容量检查直接读取已保存的结果。配置准备阶段、任务接收周期和缓冲容量保持不变。

部分和银行数量按 `SHARED_PHYSICAL_BANKS_WIDTH` 保存，完整 32 位输入先执行范围检查。生产配置使用三位银行数量和一位合法性状态。关闭共享存储时，公开银行数量保持为四。

## 时序等价验证

`run_formal.py` 从真实 `npu_top.sv` 提取配置声明和完整接收逻辑，再接入实际 `ps_capacity_limits`。输入配置保留全部 32 位，接收、容量采样和复位序列均不受限制。参考版本为 `087542cb`。

六至九个物理银行分别覆盖 2,048、4,096、8,192 字节容量，另覆盖两种关闭共享存储的配置。十四组时序归纳共 4,728 个比较位全部通过，包含默认分配、完整 32 位无效配置和连续配置接收。

`test/ps_capacity_limits/run_top_formal.py` 使用已证明的派生状态关系检查顶层容量表达式；十二组配置的四项性质全部通过。检查包括原始容量标志、部分和容量标志、配置无效标志和单命令行数。

## 综合与路径

测量对象包含实际配置寄存器、全部银行派生计算、完整容量常量表及容量结果寄存器。参数为七个物理银行、每银行 8,192 字节、最大 512 行、五位帧数；宽算术映射使用最小位宽 8 和 DSP 预算 740。

| 映射方式 | 参考逻辑 LUT | 当前逻辑 LUT | 参考 FF | 当前 FF | 参考 DSP | 当前 DSP | 参考寄存器最长路径 | 当前寄存器最长路径 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 原生 LUT 映射 | 183 | 74 | 34 | 38 | 2 | 1 | 13 | 6 |
| 物理面积成本映射 | 147 | 90 | 34 | 38 | 2 | 1 | 13 | 6 |

寄存器至部分和银行数量、分配无效标志的组合边界均由四级变为零级。配置输入到新寄存器的最长路径在物理面积成本映射中为七级。路径按实际 LUT、进位单元和 DSP 内部寄存器边界统计；整机资源与跨模块路径由完整 SoC 综合统计。

`measurement.json` 保存源文件 SHA-256、正式证明参数、映射资源及路径摘要。

## 复现

```bash
python3 test/ps_allocation_registration/run_formal.py --out build/ps_allocation_registration/formal
python3 test/ps_capacity_limits/run_top_formal.py --out build/ps_allocation_registration/capacity_formula --reference-rev 087542cb --bank-bytes 2048 4096 8192
python3 test/ps_allocation_registration/prepare_measurement.py --out build/ps_allocation_registration/inputs
```

将生成的 `cases.json` 交给 `scripts/fpga/open_fpga_synth.py --case-config`，选择 `allocation_reference`、`allocation_current`，并增加 `--wide-alu-dsp-budget 740 --wide-alu-minimum-width 8`。物理面积成本映射使用 `scripts/fpga/remap_fpga_luts.py --mode physical-cost`。

`measure_paths.py` 接收映射结果的 `mapped.json` 和对应 `pre_lut.il`，分别统计内部寄存器路径、分配结果边界和配置输入采样边界。
