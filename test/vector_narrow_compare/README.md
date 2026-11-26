# 向量窄位算术比较

池化限幅将两个有符号八位输入扩展为九位，再使用差值的符号位检查激活边界。每个通道先处理下限，再处理上限，全部八路通道同周期计算。

PE 极值比较将低半字扩展为十七位，使用差值的最高位判断无符号借位；高半字相等条件、模式选择、寄存使能和结果周期保持相同。普通减法表达式带有算术资源推断提示，代码不实例化器件原语。

## 功能检查

```sh
python test/vector_narrow_compare/run_pool.py --out build/vector_narrow_compare/pool
python test/vector_narrow_compare/run_pe.py --out build/vector_narrow_compare/pe
```

池化检查从实际 `vector_engine` 提取生成块，分别对 1、8、16 路结构进行完整输入空间的组合等价证明。检查同时确认向量引擎其余源码与参考提交逐字相同。

PE 检查比较完整时序模块，覆盖扩展乘法和预选累加输入的全部四种参数组合。所有公开输出均参与比较，外部输入保持自由。两组检查各覆盖普通 RTL、`SYNTHESIS`、`XILINX_FPGA` 及两种宏同时定义的情况。

四态仿真覆盖无序激活边界、相等操作数、完整上下边界、未知输入位、未知操作码及使能暂停。`pool_validation.json` 和 `pe_validation.json` 保存检查结果及源码散列。

## 完整模块资源比较

```sh
python test/vector_narrow_compare/measure.py --out build/vector_narrow_compare/measurement
```

测量使用 16 通道、8 个 PE、64 位总线、8 路窗口返回、共享存储及本地量化配置。参考实现和当前实现使用相同的依赖源码和映射设置，组合延迟目标为 6667 ps，连线延迟参数为 300 ps，LUT 输入上限为 8。

`measurement.json` 保存完整向量引擎的资源及实际寄存路径统计。完整 SoC 的面积和时序结果由相应整机报告提供。

已完成测量结果如下：

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 10,140 | 9,953 |
| LUTRAM 占用的 LUT | 176 | 176 |
| 寄存器 | 6,307 | 6,307 |
| DSP | 26 | 34 |
| RAMB18 | 9 | 9 |
| 完整模块最长组合级数 | 11 | 11 |

池化检查通过 12 项组合等价证明和 4,194,304 次四态结果比较；PE 检查通过 16 项完整时序等价证明和 4,194,304 次四态结果比较。向量引擎保留 16 通道、8 个 PE 和全部生产存储容量。
