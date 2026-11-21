# 量化参数装载完成条件

参数 DMA 的最后一拍根据装载后的偏移与总数决定是否继续读取。原始加法进位与三操作数压缩后的进位并行计算，乘数和移位参数两个阶段共用此条件。

设总数、当前偏移和步长分别为 32 位无符号数 `N`、`O`、`B`。令 `C` 为 `O+B` 的第 32 位，`G` 为 `O+B+2^32-N` 的第 32 位，则继续读取的条件为 `C==G`，与 `((O+B) mod 2^32)<N` 完全一致。

第二个表达式采用三操作数压缩：逐位异或给出 `compressed_sum`，多数函数给出 `compressed_carry`。低 32 位加法只需输出进位，`G` 等于该进位与 `compressed_carry[31]` 的异或。两个进位网络均按三位分组，并保留平衡归并层次。

表达式保留 32 位加法回绕行为。其他 `REG_WIDTH` 配置使用相应宽度的偏移加法与总数比较。

## 算术证明

`run_formal.py` 编译实际完成判断，对总共 96 个输入位执行无约束 SAT 证明，检查完整输入范围下是否等于原始无符号比较。

在具有相同输入、输出寄存器的生产宽度片段中，最长组合路径为 6 个单元，使用 179 个逻辑 LUT、70 个触发器和零个 CARRY4。整机结果另行统计。

## 完整功能检查

使用 64 位总线、16 个通道和 32 组 IA 复用，参考提交为 `dde5e7c9`。完整接口测试比较全部 22 个公开输出，覆盖有效周期和无效周期，共 256 个场景、528,662 个周期、209,001 组输出、958 条 DMA 命令和 6,496 个返回拍。

生产分时配置 `p_compute_lanes=4` 另完成 44,689 个周期、18,011 组输出和 576,352 个元素检查，覆盖 186 个组、7 次清空、6 次复位及 13 个满容量组。测试启用缓冲区观察断言。

上述检查使用 Yosys 提供的 Xilinx 七系列功能模型。实际 RTL 通过算术和存储描述进行资源推断。完整 SoC 的资源与路径结果由整机综合报告给出。

## 复现

```bash
python3 test/requant_load_completion/run_formal.py --out /tmp/npu_requant_load_completion
python3 test/requant_pipeline/run_interface.py \
  --reference-rev dde5e7c9 --bus-width 64 --xilinx \
  --verilator verilator --jobs 1 --out /tmp/npu_requant_interface
python3 test/requant_time_share/run.py \
  --xilinx --vlen 16 --lanes 4 --reuse 32 --bus 64 \
  --verilator verilator --out /tmp/npu_requant_serial
```

`measurement.json` 保存实际源码 SHA-256、形式证明和功能检查摘要。
