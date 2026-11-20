# 量化参数装载完成条件

参数 DMA 的最后一拍根据本次装载后的偏移与参数总数决定是否继续读取。三十二位配置使用已有的 `remaining_words`，结合加法进位和减法借位计算 `load_has_more`。乘数和移位参数两个装载阶段共用这一条件。

令总参数数为 `N`、当前偏移为 `O`、本次步长为 `B`，三者均为三十二位无符号数。令 `R` 为 `N-O` 的低三十二位，`borrow` 为该减法的借位，`carry` 为 `O+B` 的进位，`greater` 为 `R>B`。继续装载条件为：

- `borrow=0` 时，使用 `carry || greater`。
- `borrow=1` 时，使用 `carry && greater`。

该表达式保留三十二位加法回绕语义。其他 `REG_WIDTH` 配置继续使用相应宽度的偏移加法与总数比较。状态更新、DMA 命令、存储容量及所有公开输出周期保持一致。

## 综合结果

生产配置完整量化模块的逻辑 LUT 从 7,609 个减少到 7,601 个，最长寄存器间组合路径保持 15 个单元。分布式 RAM LUT 为 800 个、SRL LUT 为 160 个、触发器为 7,213 个、DSP48E1 为 96 个、RAMB18E1 为 2 个，均保持一致。完整 SoC 的物理 LUT 和器件时序通过整机实现统计。

## 功能验证

`run_formal.py` 从正式 RTL 提取实际使用的连续赋值，对 `N`、`O`、`B` 共 96 个不受约束的输入位进行 SAT 证明。完整输入范围均通过，包括加法进位、减法借位和边界值。

完整量化接口比较覆盖生产规模 `VLEN=16`、`MAX_IA_REUSE=32`、INT8/INT16 两种输出。官方 Xilinx 原语模型参与仿真。

| 总线宽度 | 场景数 | 比较周期 | 输出向量 | DMA 命令 | DMA 返回拍 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 32 | 256 | 528,662 | 206,800 | 922 | 12,322 |
| 64 | 256 | 528,662 | 209,001 | 958 | 6,496 |

全部 18 个公开输出逐周期一致。参考实现的量化 RTL 与 `5d148afe` 相同。源码和运行记录的 SHA-256 保存于 `measurement.json`。

## 复现命令

```sh
python3 test/requant_load_completion/run_formal.py \
  --out build/requant_load_completion/formal

python3 test/requant_pipeline/run_interface.py \
  --reference-rev 5d148afe --xilinx --bus-width 32 64 \
  --verilator "$VERILATOR_BIN" --jobs 2 \
  --out build/requant_load_completion/interface

python3 test/requant_sync_parameters/prepare_measurement.py \
  --reference-rev 5d148afe --out build/requant_load_completion/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_load_completion/inputs/cases.json \
  --cases reference candidate --out build/requant_load_completion/synthesis \
  --lock-file "$SYNTHESIS_LOCK"
```
