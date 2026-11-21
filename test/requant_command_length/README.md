# 量化参数 DMA 长度计算

`vec_requant_full` 使用 33 位分组前缀加法计算总数与装载偏移之差。最高位保留借位，低 32 位保留完整模宽差值。装载偏移超过总数时返回零，其余情况将字数饱和到 `VLEN`。

饱和后的字数使用 `$clog2(VLEN+1)` 位保存。对于非零字数 `n`，每拍读取 `B=BUS_WIDTH/32` 个参数字，突发长度为 `(n-1)/B`；字数为零时长度字段为零。末拍编号与借位、上限检查并行计算。

## 算术证明

`run_formal.py` 提取实际长度表达式，比较全部 32 位字数和 8 位突发长度。总数与偏移均为不受约束的 32 位输入，包含相等、下溢和最大值情况。

12 组参数覆盖 `BUS_WIDTH=32、64、96、128` 和 `VLEN=1、3、16、32、256、1024` 的对应组合，全部通过 SAT 证明。

## 完整功能检查

使用 64 位总线、16 个通道和 32 组 IA 复用，参考提交为 `dde5e7c9`。完整接口测试比较全部 22 个公开输出，覆盖有效周期和无效周期，共 256 个场景、528,662 个周期、209,001 组输出、958 条 DMA 命令和 6,496 个返回拍。

生产分时配置 `p_compute_lanes=4` 另完成 44,689 个周期、18,011 组输出和 576,352 个元素检查，覆盖 186 个组、7 次清空、6 次复位及 13 个满容量组。测试启用缓冲区观察断言。

上述检查使用 Yosys 提供的 Xilinx 七系列功能模型。实际 RTL 通过算术和存储描述进行资源推断。完整 SoC 的资源与路径结果由整机综合报告给出。

## 复现

```bash
python3 test/requant_command_length/run_formal.py --out /tmp/npu_requant_command_length
python3 test/requant_pipeline/run_interface.py \
  --reference-rev dde5e7c9 --bus-width 64 --xilinx \
  --verilator verilator --jobs 1 --out /tmp/npu_requant_interface
python3 test/requant_time_share/run.py \
  --xilinx --vlen 16 --lanes 4 --reuse 32 --bus 64 \
  --verilator verilator --out /tmp/npu_requant_serial
```

`measurement.json` 保存实际源码 SHA-256、形式证明和功能检查摘要。
