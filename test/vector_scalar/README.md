# 标量有符号乘法验证

`vector_scalar_multiplier` 每周期接收两个 INT32 操作数，经过两个时钟边沿输出完整 INT64 乘积。该接口持续运行，内部复用独立文件中的 `registered_multiplier_s32`。

乘法器先保存四个部分积。低半字按无符号数扩展，高半字保留符号。下一阶段将高半字乘积、两个交叉部分积和低半字乘积的高十六位组合为完整乘积。三项上半部先压缩为和与进位，再执行四十八位模加法。低十六位与上半部在同一边沿保存。

| 时钟边沿 | 部分积寄存器 | 结果寄存器 |
| --- | --- | --- |
| E0 | 保存输入 0 的四个部分积 | 保存前一个输入的完整结果 |
| E1 | 保存输入 1 的四个部分积 | 保存输入 0 的完整结果 |
| E2 | 保存输入 2 的四个部分积 | 保存输入 1 的完整结果 |

独立模块的 `p_input_register` 与 `p_b_input_register` 分别控制两个输入寄存阶段。`i_en` 同时控制全部寄存阶段，暂停期间保持操作数、部分积和结果。

## 验证方法

```bash
python3 test/vector_scalar/run.py --out build/vector_scalar \
  --simulate --verilator verilator
```

也可使用 Icarus 执行相同的独立数值测试：

```bash
python3 test/vector_scalar/run.py --out build/vector_scalar_iverilog \
  --simulate --simulator iverilog
```

形式检查比较完整乘积及寄存关系。数值测试使用独立 INT64 乘法计算期望值，检查符号极值、交替位模式、每个低半字值以及一百万组随机输入，共 1,134,340 个完整结果；每次同时核对低十六位与高四十八位的采样周期。

四种输入寄存配置、任意使能和 `X/Z` 传播由 `test/vector_scalar_dsp_pair/run.py` 检查。输出目录中的 `summary.json` 记录源文件 SHA256、证明结果和数值检查计数。`--synthesis` 可额外调用工程开源综合入口生成资源报告。
