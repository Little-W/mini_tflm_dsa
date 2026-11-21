# 标量乘法器验证

`run.py` 检查 `registered_multiplier_s32` 的完整 64 位有符号乘积、输入寄存选项和统一时钟使能。参考实现通过 `--reference` 指定，待测实现默认使用仓库中的 `vector_scalar_multiplier.sv`。

## 检查内容

- 对 `p_input_register`、`p_b_input_register` 和 `p_use_dsp` 的八种组合执行时序等价证明，允许输入操作数和 `i_en` 在任意周期变化。
- 使用四态仿真逐周期比较完整输出，覆盖操作数中的 `X`、`Z`、使能暂停和未知使能。
- 在 `summary.json` 中保存实现、参考文件、公共加法器和测试代码的 SHA256，以及各项检查结果。

默认输入寄存配置下，乘法器经过两个有效时钟边沿输出结果；持续使能时每个周期可接收一组操作数。暂停期间，部分积与结果同时保持。

## 运行方法

在仓库根目录执行以下命令。环境需要 Python、Pyosys、Icarus Verilog 和 `vvp`。

```bash
mkdir -p build/vector_scalar_reference
git show 6617626d:rtl/npu/conv/vector_scalar_multiplier.sv > build/vector_scalar_reference/vector_scalar_multiplier.sv
python test/vector_scalar_dsp_pair/run.py \
  --reference build/vector_scalar_reference/vector_scalar_multiplier.sv \
  --out build/vector_scalar_dsp_pair_check
```

工具路径可使用 `--iverilog` 和 `--vvp` 指定。待测候选文件可使用 `--source` 指定。
