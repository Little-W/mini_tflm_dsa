# 标量偏置地址碰撞与同步读取使能

`bias_scalar_word_match` 直接比较标量基址与索引的模加结果所在的数据字。对于每个数据字包含二的幂个元素的配置，低位和值确定字内位置，其他位通过相邻位的进位关系并行比较。一般配置继续使用完整地址运算。输入包含未知位时，结果保持完整加法和除法的四态语义。

`bias_read_enable_select` 在最后一级合并后续标量碰撞结果与其他读取分支。偏置缓冲区的实际写入接受条件、同址写入时的输出保持、存储字节掩码、所有数据与状态寄存器均保持原有逐周期行为。

## 验证

通用 Slang 配置显式使用 `-USYNTHESIS -UXILINX_FPGA`，FPGA 配置使用 `-DSYNTHESIS=1 -DXILINX_FPGA=1`。

| 检查 | 参数和范围 | 结果 |
|---|---|---:|
| 地址比较的任意输入证明 | 10 种和值宽度、地址宽度和字内元素数，两种编译方式 | 20 项通过 |
| 地址比较四态检查 | 随机值、逐位未知值及全部未知值 | 见 `validation.json` |
| 实际读取使能组合证明 | 任意分支选择、碰撞、写入地址和掩码 | 2 项通过 |
| 实际读取使能四态检查 | 五个控制信号四态组合与随机内部结果 | 166,916 次通过 |
| 完整偏置缓冲区时序归纳 | 四种阵列、总线、数据与分组参数，两种编译方式 | 8 项通过 |

完整缓冲区证明包含实际存储数组，比较全部公开输出与共同状态，共验证 82,526 位。所有功能输入自由，证明不要求特定请求序列。源码、日志和测试摘要保存在 `validation.json`。

## 完整缓冲区测量

比较使用相同参数：`SIZE=16`、`DATA_WIDTH=32`、`DMA_DATA_WIDTH=8`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=28`、`GROUP_BLOCKS_MAX=32`，并启用共享装载索引和已保存的当前范围资格。

| 项目 | 参考输入 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 530 | 537 |
| 寄存器之间的最长组合单元数 | 8 | 9 |
| `group_read_idx` 到实际 RAM `ENARDEN` | 7 | 4 |
| `group_read_idx` 到实际 RAM 地址端口 | 4 | 4 |

两版的存储容量、并行操作和端口时序相同。映射采用 `physical-cost`、6,667 ps 目标、300 ps 连线代价和最多 8 个输入的切割设置。路径直接读取真实映射网表，完整内容保存在 `measurement.json`。

## 重复执行

```sh
python test/bias_scalar_word_match/run.py --out build/bias_scalar_word_match --full
python test/bias_scalar_word_match/run_enable.py --out build/bias_read_enable
```

`--full-only` 只执行两种编译方式下的完整缓冲区证明。`run_enable.py` 直接提取实际缓冲区内的选择、写入接受和读取使能过程。
