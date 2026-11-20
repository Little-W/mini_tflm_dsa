# 偏置组首读取地址

`npu_top` 在配置接收时清零组合读索引，在有效 IS 输出时计算下一行索引。组首读取由 `group_read_start = is_mode && send_ia_trigger && !bias_sleep` 交给偏置缓冲区，缓冲区直接选择当前组基址。组首触发后的行索引寄存器仍在原有边沿清零。

## 完整缓冲区验证

`run_formal.py` 从实际 `npu_top.sv` 提取读索引计算和 `group_read_start` 连接，接入完整 `bias_loader_buffer.sv`。参考版本使用 `bdd7109f` 的读索引计算；两个比较对象使用相同的当前缓冲区。

两侧存储返回端接受同一任意 64 位值，每个周期均可变化。全部读写地址、使能、写掩码和写数据逐周期相同，因而相同初始存储能够保持每一个存储位相同。验证同时比较缓冲区所有寄存器、缓存数据和公开输出，输入、配置、暂停与触发序列均不受限制。

六组配置共 8,549 个比较位全部通过：

| SIZE | BUS_WIDTH | COUNT_WIDTH | GROUP_BLOCKS_MAX |
|---:|---:|---:|---:|
| 4 | 32 | 1 | 1 |
| 16 | 32 | 12 | 4 |
| 16 | 64 | 29 | 32 |
| 16 | 128 | 29 | 32 |
| 16 | 64 | 32 | 64 |
| 32 | 64 | 32 | 1 |

两个内部组合读索引信号可以采用不同值，其余完整状态、存储操作和公开输出保持一致。所有比较均使用实际源码提取结果；测试脚本检查顶层条件修改范围及缓冲区接口。

## 综合与路径

测量包含实际索引计算、完整偏置缓冲区和实际 `REGFILE`，参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`。宽算术映射使用最小位宽 8 和 DSP 预算 740。

| 映射方式 | 参考逻辑 LUT | 当前逻辑 LUT | 参考组首触发至 RAM 地址 | 当前组首触发至 RAM 地址 |
|---|---:|---:|---:|---:|
| 原生 LUT 映射 | 544 | 543 | 6 | 4 |
| 物理面积成本映射 | 522 | 521 | 5 | 2 |

两种实现均使用 773 个触发器、4 个 DSP 和一个 `RAMB36E1`，内部寄存器最长路径为 11 级。路径测量在分析图中将 `send_ia_trigger` 视为寄存器输出，终点为实际 RAM 地址端口；RTL 没有增加寄存器或周期。完整 SoC 的上游控制路径由整机综合继续统计。

`measurement.json` 保存正式证明配置、源文件 SHA-256、映射资源和路径摘要。

## 复现

```bash
python3 test/bias_group_index/run_formal.py --out build/bias_group_index/formal
python3 test/bias_group_index/prepare_measurement.py --out build/bias_group_index/inputs
```

将生成的 `cases.json` 交给 `scripts/fpga/open_fpga_synth.py --case-config`，选择 `bias_index_reference`、`bias_index_current`，并增加 `--wide-alu-dsp-budget 740 --wide-alu-minimum-width 8`。物理面积成本映射使用 `scripts/fpga/remap_fpga_luts.py --mode physical-cost`。

`measure_paths.py` 接收每个映射结果的 `mapped.json` 和对应 `pre_lut.il`，测量组首触发到实际 RAM 地址端口的路径。
