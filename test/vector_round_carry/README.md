# 向量舍入与输出限幅

生产实现位于 `rtl/npu/conv/vector_round_shift.sv` 和 `rtl/npu/conv/vector_engine.sv`。最近偶数舍入、六十四位偏移相加和输出限幅保持既有结果、寄存器更新周期及公开接口。新增组合逻辑使用显式位宽、符号和进位，没有增加 RTL 函数。

## 运算结构

`vector_round_shift` 保留原有移位阶段和可选中间寄存器。末端递增分成两个三十二位部分：低半部接收舍入递增，高半部在递增有效且低三十二位全部为一时递增。两个部分的进位条件直接读取移位后的商，连续进位最多经过三十二位。

输出偏移是有符号三十二位数。与六十四位舍入结果相加时，低三十二位产生和与进位，高三十二位只会保持、递增一或递减一。限幅逻辑并行判断高位结果是否为零、是否为全一以及符号，由此判断完整和是否处于 INT32 范围。范围内使用低三十二位进行有符号比较，范围外根据完整和的符号选择限幅端点。低端比较保持优先级，完整六十四位加法的回绕行为保留。

## 完整向量引擎综合

比较采用 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64`，启用 `SYNTHESIS` 和 `XILINX_FPGA`。参考提交为 `1c081bc`，两次综合使用相同工具和其他 RTL。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 13,092 | 13,149 |
| 分布式 RAM LUT | 248 | 248 |
| 触发器 | 6,104 | 6,104 |
| DSP48E1 | 16 | 16 |
| CARRY4 | 885 | 872 |
| 最长寄存器间组合路径 | 24 | 19 |
| 中间舍入寄存器至结果寄存器 | 24 | 18 |
| 输出偏移至结果存储 | 23 | 19 |

组合单元数量根据综合网表的实际连接计算。150 MHz 时序由目标器件的完整布局布线分析检查。

## 验证

舍入模块在 `REGISTER_MIDDLE=0` 和 `REGISTER_MIDDLE=1` 两种配置下完成全输入等价检查，分别覆盖 456 位和 524 位状态与输出。偏移与限幅检查直接提取生产源码的表达式，对任意六十四位舍入结果、输出偏移及两个限幅值证明完整三十二位结果相同。

完整向量测试使用官方 Xilinx 原语功能模型和独立整数数值参考。BUS32、BUS64 各完成 592 项任务，分别检查 168,491 个和 169,361 个输出，任务周期分别为 2,998,186 和 2,995,967。覆盖深度卷积、池化、向量计算、Add、Softmax、DMA 等待和输出写回。构建记录确认测试期间及测试完成后源码一致。

资源、路径、源码、功能模型、仿真程序和运行报告的摘要保存在 [measurement.json](measurement.json)。

## 运行命令

```bash
python3 test/vector_round_carry/run_formal.py --out build/vector_round_formal --reference-ref 1c081bc
python3 test/vector_round_carry/run_offset_formal.py --out build/vector_offset_formal --reference-ref 1c081bc
python3 test/vector_engine/run.py --out build/vector_round_bus32 --bus-width 32 --pes 8 --xilinx --verilator verilator-modern --jobs 2
python3 test/vector_engine/run.py --out build/vector_round_bus64 --bus-width 64 --pes 8 --xilinx --verilator verilator-modern --jobs 2
python3 test/vector_round_carry/synthesis.py --out build/vector_round_synthesis --reference-ref 1c081bc
```
