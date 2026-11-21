# 量化尾部通道与复用组计数

`vec_requant_full` 计算当前块的有效通道、有效行和复用组所需行数。块起点保留 32 位左移与截断语义。尺寸为二的幂且寄存器宽度足够时，高位比较与尾部低位选择并行完成；其他参数使用完整的饱和表达式。

复用组容量检查先将组起点、组容量和尺寸反码压缩为两项，再使用分组前缀进位判断边界。剩余行数与容量判断并行计算。块坐标、组边界和后续块位置保持相同的更新周期。

## 算术证明

`run_formal.py` 提取实际生产表达式，对完整尺寸、块坐标、复用参数及模式使用无约束输入。比较结果包含有效通道数、行数、复用组行数、量化数量、参数索引、组内位置和全部块推进标志，最多比较 264 位结果。

15 组参数覆盖 `VLEN=1、2、3、7、16、32、1024、65536、131072、1073741824` 与 `REG_WIDTH=4、16、32、64` 的对应组合，全部通过 SAT 证明。

## 完整功能检查

使用 64 位总线、16 个通道和 32 组 IA 复用，参考提交为 `dde5e7c9`。完整接口测试比较全部 22 个公开输出，覆盖有效周期和无效周期，共 256 个场景、528,662 个周期、209,001 组输出、958 条 DMA 命令和 6,496 个返回拍。

生产分时配置 `p_compute_lanes=4` 另完成 44,689 个周期、18,011 组输出和 576,352 个元素检查，覆盖 186 个组、7 次清空、6 次复位及 13 个满容量组。测试启用缓冲区观察断言。

上述检查使用 Yosys 提供的 Xilinx 七系列功能模型。实际 RTL 通过算术和存储描述进行资源推断。完整 SoC 的资源与路径结果由整机综合报告给出。

## 复现

```bash
python3 test/requant_tail_count/run_formal.py --out /tmp/npu_requant_tail_count
python3 test/requant_pipeline/run_interface.py \
  --reference-rev dde5e7c9 --bus-width 64 --xilinx \
  --verilator verilator --jobs 1 --out /tmp/npu_requant_interface
python3 test/requant_time_share/run.py \
  --xilinx --vlen 16 --lanes 4 --reuse 32 --bus 64 \
  --verilator verilator --out /tmp/npu_requant_serial
```

`measurement.json` 保存实际源码 SHA-256、形式证明和功能检查摘要。
