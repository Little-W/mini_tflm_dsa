# FIFO 行结束判断

## 实现

FPGA 的二次幂银行配置先分别计算各银行的行结束条件，再通过固定六路逻辑或树选择结果。通用实现及其他银行数量保留索引选择行为。

`co_row_limit_q` 与行号同步保存比较上限，始终满足：

```systemverilog
co_row_limit_q == COUNT_WIDTH'(co_row[3:0]) + COUNT_WIDTH'(1)
```

复位和组启动时，上限置为一。行完成时，先计算四位行号的下一值，再按 `COUNT_WIDTH` 转换并加一。该顺序同时保留四位行号回绕和计数宽度截断。其他周期保持原值。生产配置增加五个位的状态，不改变公开输出周期、存储容量或存储端口。

## 形式验证

参考提交为 `a0e01073`。七组配置共完成 **10,221 位**等价比较，覆盖全部控制状态、公开输出及存储读写端口。读数据和外部输入不受限制，实际存储实现保持相同。

两份形式模型保留同名 `formal_co_row_limit`：参考模型连接完整加法表达式，当前模型连接实际寄存值。该关系参与逐位时序归纳，与控制及端口输出一同验证。

| VLEN | 银行数量 | 总线宽度 | 循环存储 | 实现 |
| ---: | ---: | ---: | ---: | --- |
| 16 | 32 | 32 | 1 | FPGA |
| 16 | 32 | 64 | 1 | FPGA |
| 16 | 3 | 64 | 1 | FPGA |
| 16 | 16 | 64 | 1 | FPGA |
| 16 | 32 | 64 | 1 | 通用 |
| 16 | 32 | 64 | 0 | FPGA |
| 8 | 8 | 32 | 0 | FPGA |

## 实际映射

联合测量实例化真实 `oa_writer` 和 32 个银行的循环 INT8 FIFO，使用 `VLEN=16`、`BUS_WIDTH=64`、写回 `COUNT_WIDTH=28`，全部公开数据和控制输出参与综合。

| 资源 | 参考提交 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,904 | 2,955 |
| 触发器 | 1,051 | 1,051 |
| RAMB18E1 | 8 | 8 |
| DSP48E1 | 0 | 0 |

当前 `bank_count` 至 `bank_count` 为 **13 级**，`co_row` 至 `bank_count` 为 **8 级**，`co_row_limit_q` 至 `bank_count` 为 **13 级**。包括写回模块输入影响在内，全部 FIFO 同步端点的最长组合路径为 **13 级**。

联合模块总最长为 18 级，位于 `oa_writer.cfg_is_mode` 至写回行列配置寄存器。该文件在本次修改中保持相同。完整 SoC 的算术映射和物理实现由整机测量记录。

## 数值与周期

官方 FPGA 原语分支在 16 和 32 个银行、32 位和 64 位总线四种组合下均通过。每组 81 个场景、12,392 个输出字节，合计 **324 个场景、49,568 个输出字节**。参考实现与当前实现每周期比较数据、掩码、有效信号、行切换、请求和满状态。

`measurement.json` 保存源码摘要、形式结果、每组数值结果、实际连接路径及网表摘要。

## 复跑

```sh
python3 test/fifo_byte_rotation/run_formal.py --reference a0e01073 --out build/fifo_row_predicate/formal
python3 test/writeback_cyclic/run.py --reference-rev a0e01073 --banks 32 --bus-width 32 --fpga --out build/fifo_row_predicate/bus32
python3 test/writeback_cyclic/run.py --reference-rev a0e01073 --banks 32 --bus-width 64 --fpga --out build/fifo_row_predicate/bus64

python3 test/oa_fifo_timing/prepare_measurement.py --reference a0e01073 --out build/fifo_row_predicate/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config build/fifo_row_predicate/inputs/cases.json --cases reference current --out build/fifo_row_predicate/synthesis --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/fifo_row_predicate/measure_paths.py --reference build/fifo_row_predicate/synthesis/reference --current build/fifo_row_predicate/synthesis/current --out build/fifo_row_predicate/paths.json
```
