# 量化裁剪与列结束比较验证

量化裁剪将完整三十五位有符号值的最高位取反，再用 `unsigned_compare` 计算大小关系。FPGA 综合可将低位段和高位段减法推断为算术资源。输入包含 X/Z 时使用原有分组关系的四态结果。列结束判断复用三位分组比较，随后归并全部相等条件。

## 功能检查

`run.py` 以提交 `a235227e` 为参照，对普通、`SYNTHESIS`、`XILINX_FPGA` 及两者同时定义的模式分别检查两种参数读取时序，共八项完整 `requant_compute_lane` 逐周期等价证明。全部公开输出参与比较，外部输入不附加约束。

四态检查覆盖裁剪上下限、完整三十五位输入、暂停、清空、复位、有效位及通道使能，执行 524,288 次比较。独立数值回归的四种配置各运行 1,057,912 个周期，检查 850,859 个输出结果。

生产配置使用接口等价和组合替换证明。实际算术通道已经按两种参数读取时序完成接口证明；列比较连接到已证明的完整相等函数后，`vec_requant` 与参照源码逐字一致。脚本同时检查其余依赖逐文件保持相同。两个物理量化通道、五百一十二行输入容量、全部参数存储和公开周期行为保持不变。

## 运行方法

```bash
python test/requant_bound_comparison/run.py --out build/requant_bounds_final --jobs 2
python test/requant_bound_comparison/measure.py --out build/requant_bounds_measure
python test/requant_compute_lane/run.py --out build/requant_bounds_numeric_final \
  --variants generic fpga --delayed-parameters 0 1 --jobs 2
python test/requant_compute_lane/run_formal.py --out build/requant_bounds_tail_control
```

`validation.json`、`numeric_validation.json` 和 `control_validation.json` 保存完整检查结果及源码哈希。`measurement.json` 保存相同工具配置下的完整父模块资源和实际寄存器连接路径。

## 资源与组合级数

映射使用 `physical-cost`、6667 ps 目标、300 ps 布线代价及最多八个 LUT 输入。

| 完整模块 | 修改前逻辑 LUT | 当前逻辑 LUT | 修改前寄存器间最长级数 | 当前寄存器间最长级数 |
| --- | ---: | ---: | ---: | ---: |
| `requant_compute_lane` | 442 | 391 | 9 | 6 |
| `vec_requant`，两个物理通道 | 2363 | 2262 | 10 | 10 |

完整量化模块减少 101 个逻辑 LUT，DSP 由 14 个增加到 18 个。1290 个寄存器、64 个 LUTRAM、14 个 SRL 和 19 个 RAMB18 保持不变。RTL 使用普通算术和比较表达式，由综合工具推断资源。
