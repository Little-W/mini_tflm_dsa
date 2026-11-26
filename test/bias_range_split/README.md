# 偏置请求范围的分段算术

`bias_request_end_compare` 接收完整起点、长度和驻留结束位置，输出请求末端是否越界。范围宽度为 24 至 46 位时，压缩后的两个加数分别采用平衡低段、高段原生加法，高段传播条件并行生成最高进位。综合工具据此推断 DSP 算术资源。未知输入使用既有分组传播表达式。

模块端口、计数宽度、偏置容量、读写次序及所有寄存边沿均保持。生产配置的 29 位计数对应 30 位范围，分成两个 15 位段。

## 验证

`run.py` 对参考提交 `c42f5ff9` 和当前模块的全部公开输出进行比较。13 个计数宽度覆盖 1 至 47 位及实现切换边界；每个宽度分别验证通用、`SYNTHESIS`、`XILINX_FPGA`、两项同时定义的模式。

- 52 项无输入约束的组合形式等价证明通过。
- 3,407,872 次严格四态输出比较通过，包含随机值、相等边界、溢出及局部和整体 X/Z 输入。
- 实际 `bias_loader`、`bias_loader_ctrl`、`bias_loader_buffer` 和 `bias_resident_qualify` 与参考提交逐字节一致，替换组件的所有输入自由，因而组成后的完整父模块保持逐周期行为。
- 既有偏置驻留与读取测试在通用及 FPGA 模式各通过 392 项，覆盖 1、2、4、8、16、32 块容量、32/64 位总线、WS/IS 读取、重复分组和末端分组。

运行命令：

```bash
python test/bias_range_split/run.py --out build/bias_range_split
python test/bias_range_split/measure.py --out build/bias_range_split_measurement
python test/bias_loader_reuse/run.py --out build/bias_range_split_reuse
python test/bias_loader_reuse/run.py --fpga --out build/bias_range_split_reuse_fpga
```

## 完整偏置模块测量

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`DATA_WIDTH=32`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=16`。采用项目相同的 `physical-cost` 映射、6,667 ps 目标、300 ps 布线参数和最大 8 输入 LUT。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,215 | 1,191 |
| 最长寄存器组合路径 | 13 | 10 |
| DSP | 3 | 5 |

完整资源数、关键路径和输入文件摘要保存在 `measurement.json`；形式与四态结果保存在 `validation.json`；偏置读取测试结果保存在 `reuse.json`。
