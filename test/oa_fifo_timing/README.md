# 输出组行数与 FIFO 启动控制

`oa_writer` 在准备初始组和后续组行数时，同时保存对应的行分块数量。组切换时，两者在同一个边沿更新。`coalesce_row_tiles` 直接选择已保存的分块数量，配置接收、写请求、DMA 描述符、输出握手和完成周期保持一致。

`vec_s8_to_fifo_full` 的组启动条件并行检查截断乘积是否非零。保留乘积低 `W` 位时，输入中至少存在一对置位的位索引之和小于 `W`，等价于该截断乘积非零。该关系用于启动控制，实际分块乘积继续用于后续地址更新。所有输入范围均保留，包括截断乘积为零的情况。

## 连接路径与资源

联合测量实例化真实 `oa_writer` 与 32 个存储块的循环 INT8 FIFO，保持 `VLEN=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=28`，全部公开数据和控制输出参与综合。参考提交为 `b7a2af3d`，采用 Yosys 0.71、ABC9 和 Xilinx 7 系列原语。

| 项目 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,906 | 2,904 |
| 触发器 | 1,036 | 1,051 |
| RAMB18E1 | 8 | 8 |
| DSP48E1 | 0 | 0 |
| 组行数或分块寄存器至 FIFO 数据有效寄存器 | 15 级 | 11 级 |
| 联合模块最长寄存器间组合路径 | 18 级 | 18 级 |

新增的十五个触发器保存三组五位分块数量。存储容量与端口不变。完整 SoC 使用独立的算术映射与全局优化，整机组合路径及物理 LUT 由对应固定版本报告记录。

## 功能检查

- 七组写回参数完成时序归纳，比较全部公开输出和 61 个原有状态信号，并证明三个新增寄存结果与其行数的关系。首个边沿复位，后续输入不受约束。
- 截断乘积的 1 至 12 种保留位宽全部完成输入证明，每组覆盖两个任意 32 位输入。
- 七组 FIFO 配置完成 10,156 位等价比较，覆盖完整控制状态、公开输出和全部存储读写端口。存储读数据不受约束，存储实现保持相同。
- 四组写回参数完成 1,024 个场景、568,789 个周期，检查 17,667 个 DMA 命令、3,439 个合并组、501 次正常完成和 390 次运行中断。
- 实际 FPGA 分支的 BUS32、BUS64 FIFO 各完成 81 个场景，合计检查 24,784 个输出字节，数据和周期均一致。

`measurement.json` 保存当前源码、参考源码、原语库、证明记录、仿真程序及实际综合网表的 SHA-256。

## 运行

```sh
python3 test/oa_fifo_timing/run_formal.py --out build/oa_fifo_timing/writer_formal
python3 test/fifo_byte_rotation/run_formal.py \
  --reference b7a2af3d --out build/oa_fifo_timing/fifo_formal
python3 test/oa_writer/run_equivalence.py --reference b7a2af3d \
  --out build/oa_fifo_timing/writer_numeric --verilator verilator-modern \
  --profiles 4:32:8 16:32:28 16:64:28 32:64:32 --scenarios 256 --cycles 1024
python3 test/writeback_cyclic/run.py --reference-rev b7a2af3d \
  --out build/oa_fifo_timing/fifo_numeric_bus32 --bus-width 32 --fpga
python3 test/writeback_cyclic/run.py --reference-rev b7a2af3d \
  --out build/oa_fifo_timing/fifo_numeric_bus64 --bus-width 64 --fpga

python3 test/oa_fifo_timing/prepare_measurement.py --out build/oa_fifo_timing/synthesis_inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/oa_fifo_timing/synthesis_inputs/cases.json \
  --cases reference current --out build/oa_fifo_timing/synthesis
python3 test/oa_fifo_timing/measure_paths.py --synthesis build/oa_fifo_timing/synthesis
```
