# 偏置行边界计算

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`npu_top.sv` 使用扩展一位的完整差值 `有效行数 - 当前行号 - 1` 形成偏置行回绕条件。差值符号位或全零表示当前行递增后达到有效行数；有效行数不大于一时直接回绕。行读取索引和行索引寄存器共用这个结果。

差值采用普通 RTL 算术表达式，并以 `use_dsp` 属性指导综合。行索引的保持、递增、组首清零和异步低有效复位保持原有采样边沿，接口没有增加周期。

## 验证

参考版本为 `cfcc1a95ddcd93625636efc15b8c2b2b1835730f`。测试从实际顶层提取完整偏置组状态、行索引及其组合依赖。

| 范围 | 覆盖 | 结果 |
| --- | --- | --- |
| 完整偏置控制状态与输出 | 8 组参数，各含 FPGA 和通用配置 | 14,057 个比较位通过 |
| 实际行边界与下一行表达式 | 9 种行容量，30,000 组二态及四态输入 | 3,030,000 次输出位比较通过 |
| 完整偏置缓冲区连接 | 6 组阵列、总线和计数宽度 | 9,433 个比较位通过 |

状态证明不限制配置值、触发时刻或暂停序列。缓冲区比较同时检查所有存储读写端口、寄存器和公开输出；两侧存储返回端接受逐周期变化的同一任意值。

## 独立综合

测量使用生产参数 `SIZE=16`、`REG_WIDTH=32`、`BIAS_GROUP_BLOCKS_MAX=32`，包括完整偏置组状态和行索引。两侧使用相同的依赖和综合选项。

| 指标 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 标称 LUT | 214 | 192 |
| 触发器 | 103 | 103 |
| DSP | 5 | 6 |
| 完整控制块最长组合路径 | 8 级 | 6 级 |

这些数值来自独立模块映射。完整 SoC 的资源和组合路径由相同版本的整机报告给出；150 MHz 时序需要对应器件的布局布线报告。

## 复现

```sh
python3 test/bias_row_distance/run.py --out build/bias_row_distance/formal
python3 test/bias_group_index/run_formal.py \
  --reference-rev cfcc1a95 --out build/bias_row_distance/buffer
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/bias_row_distance/formal/cases.json \
  --cases reference current --out build/bias_row_distance/synthesis
```

`validation.json` 保存源码校验值、参数、状态比较数量与综合结果。
