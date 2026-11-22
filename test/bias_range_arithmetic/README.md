# 偏置驻留范围的完整算术

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`bias_loader_buffer` 为每个请求计算扩展一位的末端位置，再与两个银行各自保存的末端位置并行相减。差值最高位直接表示无符号借位，因此范围判定保留起点、请求长度和银行末端的全部有效位。起点范围检查、银行加载状态、活动银行选择和 WS 缓存资格共同确定偏置数据是否可用。

加法与减法使用普通 RTL 运算和 `use_dsp` 综合属性。寄存器、存储端口和接口周期保持不变。事件仿真采用完整的进位表达式，保留原有四态结果。

## 验证

从实际缓冲区源码提取范围比较部分，在计数宽度 1、2、3、8、12、28、29、32 下证明全部输入均等价。证明覆盖两个请求及两个银行的四个范围结果，输入没有范围限制。检查程序同时确认范围部分之外的缓冲区逻辑相同。八组严格四态检查共完成 160,000 组输入、640,000 次结果比较。

生产 `SYNTHESIS`／`XILINX_FPGA` 分支的完整加载器通过 392 项 DMA、WS／IS 数值、驻留与复用检查。源码 SHA-256、测试参数和结果保存在 `validation.json`。

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`。独立 Xilinx 7 系列映射结果如下。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 928 | 811 |
| 触发器 | 1,227 | 1,227 |
| DSP | 12 | 13 |
| RAMB36 | 1 | 1 |
| 完整寄存器路径最大组合级数 | 8 | 9 |

完整 SoC 的跨模块组合路径、物理 LUT 使用量和 150 MHz 时序由整机综合及布局布线结果分别确定。

## 重复运行

```sh
python test/bias_range_arithmetic/run.py --out build/bias_range_validation
python test/bias_loader_reuse/run.py --fpga --jobs 1 \
  --verilator verilator --out build/bias_range_numeric
python test/bias_range_arithmetic/prepare_measurement.py --out build/bias_range_inputs
python scripts/fpga/open_fpga_synth.py \
  --case-config build/bias_range_inputs/cases.json --cases reference current \
  --out build/bias_range_synthesis \
  --max-register-path-cells 10 --require-register-path-limit
```
