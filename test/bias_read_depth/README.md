# 偏置缓冲区范围比较与同步读取验证

## 当前设计

`bias_loader_buffer` 用扩展一位的完整范围判断驻留状态。请求起点、请求长度和银行末端先进行进位保存压缩，再用并行前缀计算越界进位；完整输入范围及溢出位均保留。两个银行分别比较，银行选择只处理最终结果。

`p_share_load_index` 默认关闭，此时装载请求与执行请求使用各自索引。实际 `bias_loader` 启用该参数：控制器只在 `S_CMD` 消费装载命中信息，且实际状态更新保证此阶段 `current_block_idx == load_block_idx`。该关系通过控制器无界归纳检查，完整加载器的状态、输出和存储操作同时进行逐周期比较。

WS 首次读取直接选择当前块起点；连续读取的地址独立计算后再选择。读使能、同步返回、缓存更新、IS 标量读取、复位和初始化优先级保持。生产配置仍保存两个银行，每个银行有 32 个分块，每块 16 个 32 位偏置，合计 32,768 bit，WS 缓存另有 512 bit。

## 检查范围

- 6 组通用缓冲区参数检查，`SIZE` 覆盖 4、8、16、32，`COUNT_WIDTH` 覆盖 1、8、12、29、32，分组容量包括非二次幂 3。输入没有范围假设。
- 5 组实际控制器索引关系的无界归纳检查，以及 5 组完整 `bias_loader` 的状态与输出等价检查。同步存储的全部地址、使能、写入数据和字节掩码均参与比较，两侧接收相同的任意存储返回值。
- 既有 `test/bias_loader_reuse` 完成 392 项实际 DMA、WS/IS 数值与驻留复用检查，包含等待、分组切换、尾块及初始化。
- 四态检查直接提取实际范围比较与读取地址表达式，覆盖每一输入位的 X/Z 注入及混合未知输入。参考表达式的已知输出位保持；部分未知输出可被并行逻辑解析为已知值。该检查不声明严格四态等价。

## 生产参数局部测量

测量完整 `bias_loader`，参数为 `SIZE=16`、`BUS_WIDTH=64`、`DATA_WIDTH=32`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`。参考版本为 `2297cb12deac56b476f9a2a656da4038a9d8a75c`，两侧采用相同普通 RTL 综合与 LUT 成本参数。

| 项目 | 参考版本 | 当前设计 |
|---|---:|---:|
| 逻辑 LUT | 1,243 | 1,180 |
| FF | 1,184 | 1,181 |
| CARRY4 | 137 | 101 |
| RAMB36E1 | 1 | 1 |
| 存储地址最长组合路径 | 16 | 8 |
| 完整加载器最长组合路径 | 16 | 14 |

完整加载器的 14 级路径位于控制器的窗口末端判断。上述结果来自开源工具的连接关系和普通 RTL 映射；实际 Vivado 面积、布线和 150 MHz 时序仍需整机报告确认。源码、工具和检查报告的 SHA-256 保存于 [measurement.json](measurement.json)。

## 复现命令

在已提供 Python Yosys/Slang、ABC、Verilator 和 Icarus 的环境中，从仓库根目录运行。`BIAS_OUT` 选择有足够空间的输出目录。

```bash
export PYTHONDONTWRITEBYTECODE=1
BIAS_OUT=/tmp/bias_read_depth
python3 test/bias_read_depth/prove.py --out "$BIAS_OUT/formal_default"
python3 test/bias_read_depth/prove_shared.py --out "$BIAS_OUT/formal_shared"
python3 test/bias_read_depth/check_four_state.py --out "$BIAS_OUT/four_state"
python3 test/bias_loader_reuse/run.py --out "$BIAS_OUT/reuse" --jobs 1
python3 test/bias_read_depth/prepare_measurement.py --out "$BIAS_OUT/inputs"
python3 scripts/fpga/open_fpga_synth.py \
  --case-config "$BIAS_OUT/inputs/cases.json" --cases reference current \
  --through pre_lut --out "$BIAS_OUT/pre"
for version in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "$BIAS_OUT/pre/$version" --out "$BIAS_OUT/mapped/$version" \
    --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
    --wire-delay-ps 500 --delay-target-ps 6667
done
python3 test/bias_read_depth/collect_report.py \
  --formal-default "$BIAS_OUT/formal_default" \
  --formal-shared "$BIAS_OUT/formal_shared" \
  --four-state "$BIAS_OUT/four_state" --reuse "$BIAS_OUT/reuse" \
  --mapped-reference "$BIAS_OUT/mapped/reference" \
  --mapped-current "$BIAS_OUT/mapped/current" \
  --out "$BIAS_OUT/measurement.json"
```
