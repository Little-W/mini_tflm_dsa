# 量化参数准备验证

`requant_pkg` 保存 INT8 与 INT16 共用的参数准备函数。INT16 乘数通过最近偶数舍入得到有符号 16 位值，再扩展为 32 位；移位准备保留完整输入范围的边界处理。`vec_requant` 在配置边沿保存原始乘数、移位量和输出精度，随后计算准备值。

```bash
python test/requant_parameter_prepare/run_formal.py --out build/requant_parameter_prepare
```

组合函数检查遍历全部 32 位乘数、全部 32 位移位参数和精度位。配置检查比较原始配置、精度和准备结果的完整 104 位状态，复位与初始化均可任意变化。INT16 功能启用与禁用分别完成函数及配置检查，共四组证明。
