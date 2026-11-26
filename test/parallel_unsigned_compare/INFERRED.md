# 宽比较的分段差值计算

FPGA 配置中，24 至 46 位的无符号比较复用 `unsigned_compare` 的两个独立差值，分别获得高、低段借位和零值条件。其余位宽以及通用配置采用三位一组的比较树。输入包含未知位时，输出沿完整关系运算传播。

全部操作保持组合计算，接口和外部寄存周期不变。RTL 使用普通减法及算术推断属性。

## 检查结果

通用和 FPGA 两种编译方式各检查 15 种位宽，每种同时检查默认参数和保留分组参数。30 项任意输入形式检查、218,232 次四态输出比较全部通过，覆盖实现选择的两侧边界及 64 位通用比较。

```bash
python3 test/parallel_unsigned_compare/run.py --out /tmp/parallel_compare_generic
python3 test/parallel_unsigned_compare/run.py --synthesis --out /tmp/parallel_compare_fpga
```

带输入、输出寄存器的独立宽比较结果如下。各配置使用一个推断的 DSP 算术单元。

| 操作数位宽 | 逻辑 LUT | 寄存器之间的组合级数 |
| --- | ---: | ---: |
| 28 | 8 | 3 |
| 29 | 8 | 3 |
| 32 | 8 | 3 |

完整模块的资源和路径由所属模块及 SoC 的综合报告记录。测试及映射数据分别保存在 `inferred_validation.json` 和 `inferred_measurement.json`。
