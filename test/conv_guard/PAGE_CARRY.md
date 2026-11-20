# 读取页范围的并行进位计算

读取保护器检查八位 `ARLEN` 与页内字地址相加后是否跨越当前页。FPGA 实现把低八位分为四组，每组通过同一个 `LUT6_2` 得到两位加法的进位与传播条件，再组合上下两个四位字段的关系。通用 RTL 使用相同的无符号范围比较。配置区间检查、32 位地址回绕处理、数据返回和所有接口周期保持。

## 固定参数结果

参考提交为 `3587da43`。配置为 32 位地址、64 位数据、四笔并发读取，以及启用 GEMM 的 4 KiB 页拆分。

| 指标 | 参考实现 | 分组进位实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 868 | 869 |
| 触发器 | 392 | 392 |
| CARRY4 | 73 | 73 |
| DSP48E1 | 0 | 0 |
| 寄存器间最长组合单元数 | 10 | 10 |
| `s_arready` 最长组合单元数 | 6 | 4 |
| 含全部公开端点的最长组合单元数 | 12 | 11 |

统计直接使用固定综合网表中的连接。端口边界仅用于表示外部时序起点与终点，生产硬件不增加寄存器。整机跨模块路径与物理 LUT 数量由完整 SoC 测量确定。

## 验证

官方 FPGA 查找表模型与通用 RTL 各完成七组完整状态和公开输出的等价比较，每种实现分别比较 5,509 位。参数覆盖 16、32、33、40 位地址，16 至 256 位数据总线，以及 GEMM 页拆分的两种配置。十一组范围表达式证明覆盖任意地址、长度、分配区间和请求格式输入。

32/64 位总线及两种页拆分配置分别运行 50,000 个周期，共比较 200,000 个周期的全部公开输出，FPGA 模型、参考实现与当前实现逐周期相同。详细源码、原语库、综合结果与路径摘要位于 [page_carry_measurement.json](page_carry_measurement.json)。

```sh
python3 test/conv_guard/prepare_page_measurement.py --out build/guard_carry/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config build/guard_carry/inputs/cases.json --cases reference current --out build/guard_carry/synthesis
python3 test/conv_guard/measure_paths.py --reference build/guard_carry/synthesis/reference --current build/guard_carry/synthesis/current --out build/guard_carry/paths.json
python3 test/conv_guard/run_control_formal.py --fpga --reference-ref 3587da43 --out build/guard_carry/fpga_formal
python3 test/conv_guard/run_control_formal.py --reference-ref 3587da43 --out build/guard_carry/generic_formal
python3 test/conv_guard/range_equivalence.py --reference-ref 3587da43 --out build/guard_carry/range_formal
python3 test/conv_guard/compare.py --fpga --reference-ref 3587da43 --verilator verilator-modern --out build/guard_carry/numeric
```
