# FIFO 组大小与行范围运算

## 实现

`vec_s8_to_fifo_full` 的组大小使用 `coalesce_rows[4:0]` 和 `coalesce_cols[4:0]` 的截断乘积。
实现先生成五个 `BANK_COUNT_WIDTH` 位部分积，再用三层进位保存归并形成两个操作数，最后执行一次加法。
每层都按银行计数宽度截断，因此保留原乘法对任意银行计数宽度的结果。
最终加法结果 `co_tile_product` 使用 `use_dsp = "yes"` 属性；本次局部映射将其中有效的三位加法推断为一个 DSP。

普通输出和转置输出的行结束判断分别计算。计数宽度大于三位时，低三位先完成 `>=` 比较，较高位的 `>`、`==` 结果与低位结果合并。
生产参数采用五位行计数，分段结构将比较组织为两级组合计算。较小计数宽度直接使用整体比较。

组大小和分段比较均使用普通 `case` 检查输入的归约结果。输入位全部已知时选择分段计算结果，其他取值使用原乘法或整体比较表达式。
读出模式的普通 `case` 继续保留按所选行数比较的默认表达式。上述逻辑保留 X/Z 传播语义，输入输出周期保持一致。

## 检查结果

参考提交为 `24f5d6cd`，参考 FIFO 的 SHA-256 为：

```text
198a8365845a46520b64f06b2115b91f734fa0356b5357ffabed8e6d52e9c7d8
```

候选 FIFO 的 SHA-256 为：

```text
b295a330ba0e1a45ed118156078b1c6e97d4fe58f0a3468bc51d630bf0d9e0c0
```

| 检查 | 范围 | 结果 |
|---|---|---|
| 组合二态等价 | 截断乘积及行比较各覆盖 1 至 32 位，共 64 项全输入 SAT 证明 | 通过 |
| 组合四态等价 | 两个五位乘法输入及两个五位比较输入分别穷举，并检查未知读出模式，共 6,291,460 次比较 | 通过 |
| 完整 FIFO 状态等价 | FPGA 10 组、通用 10 组、生产参数非预计算水位 1 组 | 全部一步归纳通过 |
| 32 位总线数值回归 | 81 项、12,392 字节、7,196 周期 | 周期差为 0 |
| 64 位总线数值回归 | 81 项、12,392 字节、4,522 周期 | 周期差为 0 |
| 四态时序回归 | 两种模式各 11 组参数、2,048 周期，共 3,696,396 次比较 | 通过 |

完整状态证明比较全部公开输出、数据存储端口及共同寄存状态。首周期复位，后续功能输入、复位和数据 RAM 返回值均由求解器自由选择。
四态时序模型保留实际控制、计数存储和数据选择，使用共同的四态数据 RAM 返回值，并比较读写地址、使能和写数据。
事件仿真模型将 `always_comb` 表示为 `always @*`。随机组行列数覆盖完整五位输入，包括本轮路径涉及的第 4 位。

`run_four_state.py` 提供 `--timeout`，默认每种模式 900 秒，并每 512 周期刷新执行进度。
详细结果和文件散列保存在 `validation.json` 与 `results/`。

## FIFO 局部映射

配置为 16 路向量、32 个银行、64 位总线、循环数据存储及预计算水位。
两份源码均使用 RTL 的 DSP 属性选择和相同的 Xilinx 7 系列映射设置。

| 指标 | 参考源码 | 候选源码 |
|---|---:|---:|
| 逻辑 LUT 单元 | 1,170 | 1,173 |
| 含分布式存储的标称 LUT | 1,230 | 1,233 |
| 触发器 | 173 | 173 |
| DSP | 0 | 1 |
| RAMB18E1 | 8 | 8 |
| 寄存器之间的最长组合单元数 | 11 | 10 |
| 包含模块输入的最长组合单元数 | 13 | 10 |

路径图完整，未发现未识别单元或组合环。150 MHz 对应的时钟周期为 6.667 ns；器件和布线延迟由布局布线后的时序报告给出。

## 复现命令

从仓库根目录运行组合检查：

```sh
python test/fifo_tile_arithmetic/run_comb.py --out build/fifo_tile_arithmetic/comb
```

运行完整状态证明：

```sh
python test/fifo_write_blocked/run_formal.py --reference 24f5d6cd --out build/fifo_tile_arithmetic/formal_fpga
python test/fifo_write_blocked/run_formal.py --reference 24f5d6cd --generic --out build/fifo_tile_arithmetic/formal_generic
python test/fifo_write_blocked/run_formal.py --reference 24f5d6cd --profile v16_n32_b64_c1 --precomputed-watermark 0 --out build/fifo_tile_arithmetic/formal_watermark
```

运行数值及四态时序回归：

```sh
python test/fifo_read_qualification/run_cycle.py --reference 24f5d6cd --bus-width 32 --out build/fifo_tile_arithmetic/numeric32
python test/fifo_read_qualification/run_cycle.py --reference 24f5d6cd --bus-width 64 --out build/fifo_tile_arithmetic/numeric64
python test/fifo_write_blocked/run_four_state.py --reference 24f5d6cd --cycles 2048 --out build/fifo_tile_arithmetic/four_state
```

运行局部映射：

```sh
python scripts/fpga/open_fpga_synth.py --case-config test/fifo_tile_arithmetic/cases.json --cases current --wide-alu-dsp-budget 740 --rtl-dsp-attributes --lock-file ../soc_small_synth.lock --out build/fifo_tile_arithmetic/mapped
```
