# 配置幂次检查

`onehot_check` 判断输入是否只有一位置位。`p_allow_zero=1` 同时接受零。检查结果为组合输出，接收结果的寄存器与控制周期保持一致。

## RTL 结构

输入按五位分组，每组产生非零标志和至少两位置位标志，再用三叉树合并。该结构使用命名生成块、明确位宽的连接以及显式布尔运算，没有自定义函数和状态寄存器。`XILINX_FPGA` 配置采用 `LUT6_2` 和 `LUT6`；通用综合配置采用等价布尔表达式。

32 位实例的 Xilinx 综合结果为 12 个逻辑 LUT、零个 `CARRY4` 和三个组合单元级。相同工具下，减一后按位与的参考表达式需要 16 个逻辑 LUT、八个 `CARRY4` 和十一个组合单元级。整个模块的结果仍需单独测量：预测器为 1,761 个逻辑 LUT、139 个 `CARRY4`；前端控制为 6,600 个逻辑 LUT、710 个 `CARRY4`。对应参考值分别为 1,764 / 146 和 6,583 / 719。前端整体最长连接为 25 个组合单元，参考值为 24；预测器均为 15。逻辑单元计数用于比较结构，150 MHz 的判定需要器件布局布线后的时序分析。

## 验证结果

- 13 种输入位宽覆盖 1 至 128 位，分别验证是否允许零与两种实现，共 52 项全部输入形式检查。查找表实现使用工具附带的官方功能模型。
- 预测器和三种帧调度器配置完成全部状态与输出的形式等价比较，共 8,412 位。
- 前端四个实际使用的检查表达式完成全部输入形式比较，其余模块内容经逐字比较一致；四组前端任务共执行 148 项任务、1,665,234 个周期，另完成 134 个控制测试周期。
- 八种共享存储配置完成顶层容量表达式的形式比较。
- 预测器完成 33 个场景、13,226 组期望结果和 206,076 个周期的公共输出比较。
- 帧调度器完成 975 个场景和 182,426 条命令，C++ 参考模型启用了未定义行为检查。

固定源码散列、测量值和各项结果保存在 `docs/data/config_onehot_validation.json`。

## 运行方法

在仓库目录中执行；需要带 Slang 的 Yosys、Pyosys 与 Verilator。

```sh
python3 test/config_onehot/run.py --out build/config_onehot --synthesize
python3 test/config_onehot/run_control_equivalence.py --out build/config_onehot_control
python3 test/config_onehot/run_frontend_equivalence.py --out build/config_onehot_frontend
python3 test/ps_capacity_limits/run_top_formal.py --out build/config_onehot_capacity --reference-rev 4df62f2
python3 test/conv_frontend/tools/compare_frontend.py --reference-ref 4df62f2 --out build/onehot_frontend_regression
python3 test/conv_replacement/predictor_test.py --build build/onehot_predictor_regression --out build/onehot_predictor_regression/summary.json --reference-ref 4df62f2
python3 test/ps_compression/run_window_scheduler.py --out build/onehot_scheduler_regression
python3 test/conv_frontend/tools/synthesis.py --out build/onehot_frontend_synth
python3 test/conv_replacement/predictor_synthesis.py --out build/onehot_predictor_synth
```
