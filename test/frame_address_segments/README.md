# 帧地址分段加法

`frame_address_prepare` 在接收一帧上下文后，依次计算输入、权重与输出三个字节地址。基址与偏移采用两个十六位普通加法并行计算，高段根据低段进位完成修正。结果继续进入原有乘积寄存阶段，地址运算保持三十二位回绕。含未知位的输入保留完整分组加法的四态传播结果。

模块使用普通算术表达式，由综合工具选择实现资源。输入接收、运算发射、结果有效、等待接收和中止恢复的周期均保持一致。

## 完整模块验证

- 分块尺寸覆盖 1、2、3、16、17、32 和 64，检查两种乘积流水配置及两种中止屏蔽配置。
- 通用与 FPGA 综合条件下完成 36 项完整模块比较，共证明 38,458 个输出与状态比较点，输入不附加功能范围限制。
- 七组四态仿真共完成 229,390 次完整输出与保存状态比较，包含复位、接收、中止、结果等待以及数据和控制信号中的 `X`、`Z`。
- 使用实际映射后的网表执行完整三十二位地址数值测试，覆盖计算的各个中止与复位阶段。

## 生产参数测量

测量参数为 `p_size=16`、`p_ready_mask_abort=1`、`p_pipeline_products=1`。两份实现使用相同 Xilinx 7 系列模型、LUT 成本、延迟目标和完整连接图检查。

| 项目 | 参照实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 509 | 477 |
| 触发器 | 542 | 542 |
| DSP | 1 | 2 |
| CARRY4 | 16 | 8 |
| 最长寄存器间组合路径 | 10 | 5 |

上述结果描述独立完整模块；跨模块路径和完整 SoC 资源使用集成测量结果。

## 复现

```bash
python3 test/frame_address_segments/run.py --out build/frame_address_segments/validation
python3 test/frame_address_segments/measure.py --out build/frame_address_segments/measurement
python3 test/frame_address/run.py \
  --mapped build/frame_address_segments/measurement/cost/current/mapped.v \
  --out build/frame_address_segments/numeric --jobs 2
```

`validation.json`、`measurement.json` 和 `numeric_validation.json` 分别保存完整模块比较、资源路径测量和实际网表数值结果，并包含相关源码、网表或执行文件的 SHA256。
