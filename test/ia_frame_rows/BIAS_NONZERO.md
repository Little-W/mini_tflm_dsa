# 偏置地址资格检查

矩阵引擎将偏置原始地址按六位分组检查，各组在同一周期形成零标志，再合并完整地址的非零条件。控制器可见位宽与完整地址一致时复用同一结果；位宽不同时分别检查控制器可见的低位。偏置加载、控制器启动资格和计算偏置输入共同使用这些结果。

检查保持原有接口、寄存器和周期。`zero_reduce` 描述普通组合归并运算，来自公共模块版本 `54a96b45`。各个分组的模块边界保持到逻辑映射阶段。

## 功能验证

`run_bias_presence.py` 直接提取实际矩阵引擎中的偏置资格表达式，同时比较完整地址及控制器可见地址的两个非零标志。参考提交为 `f45a6c21`。

- 地址宽度 1、16、31、32、33、64 的六组形式证明均通过，全部输入自由。
- 四态仿真完成 180,000 次严格比较，覆盖普通地址、零地址、模加归零、未知位和高阻位。
- 完整地址非零标志的等价关系同时覆盖偏置捕获使能和计算偏置的零值选择。

结果及源文件散列值保存在 `bias_nonzero_validation.json`。

## 独立映射

测量使用实际生产偏置资格表达式，在两种结构的输入和输出设置相同寄存器边界；权重驻留最终偏置条件按生产连接取值。使用 physical-cost 映射，目标周期 6667 ps，估算连线延迟 300 ps，最大切分输入数 8。

| 指标 | 参考结构 | 当前结构 |
| --- | ---: | ---: |
| 逻辑 LUT | 49 | 47 |
| 触发器 | 65 | 65 |
| DSP | 0 | 0 |
| 最长寄存器间组合级数 | 6 | 5 |

详细资源、路径与输入散列值保存在 `bias_nonzero_measurement.json`。以上级数属于独立表达式的映射结果，完整 SoC 的共享控制路径由整机报告统计。

## 复现

```bash
python test/ia_frame_rows/run_bias_presence.py --reference f45a6c21 --out build/bias_nonzero_verified
python test/ia_frame_rows/prepare_bias_measurement.py --reference f45a6c21 --out build/bias_nonzero_inputs
python scripts/fpga/open_fpga_synth.py --case-config build/bias_nonzero_inputs/cases.json --cases reference current --out build/bias_nonzero_pre --through pre_lut
python scripts/fpga/remap_fpga_luts.py --source build/bias_nonzero_pre/reference --out build/bias_nonzero_reference --delay-target-ps 6667
python scripts/fpga/remap_fpga_luts.py --source build/bias_nonzero_pre/current --out build/bias_nonzero_current --delay-target-ps 6667
```
