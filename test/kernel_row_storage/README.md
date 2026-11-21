# 权重缓存行存储

`kernel_loader_buffer` 保留两个逻辑预取槽位和三个物理槽位。对于大于 1 且为二的幂的 `SIZE`，每个输出通道保存一行权重，接收完整行后按列执行同步读取。输入行的数据并行写入；读地址按 `SIZE` 回绕，直接形成计算阵列要求的对角排列。其他 `SIZE` 使用按列保存的实现。

存储器采用行为级数组描述，宽写端口与窄读端口由综合工具推断。槽位交换、接收行寄存、首次发送周期、连续发送周期和清除优先级保持一致。实际读列号随读取事件保存，输出选择同时保留四态控制的行为。同周期同地址读取返回写入前的内容。

## 已完成验证

- 完整状态与存储证明覆盖 `SIZE/DATA_WIDTH` 为 `3/8`、`4/8`、`16/8`、`16/16`、`32/16` 的五组参数，共 70,539 个状态和输出比较位，其中矩阵存储为 68,184 位。三个物理槽位的每个矩阵元素均按行列位置对应，全部外部输入保持未约束。 `SIZE=32` 先证明全部存储和其余状态，再按数据位分成十六组，每组包含全部三十二个输出通道。各组沿用同一公共输入和已证明的存储对应关系，完整覆盖 512 个输出位。
- 五组逐周期数值测试各执行 100,003 个周期，总计 500,015 个周期。参数包括 `SIZE=3/4/16/32`、`DATA_WIDTH=8/16`，比较全部公开控制输出和每个权重通道，覆盖两个预取槽位、加载与发送重叠、丢弃、清除及复位。
- 相同五组参数的四态测试完成 709,565 次比较，包含未初始化读取、数据 X/Z、控制 X/Z、复位与十次同地址读写检查。
- 完整 `kernel_loader` 在 `BUS_WIDTH=32/64/128`、`COUNT_WIDTH=29/33` 下完成 855 个权重块及 218,880 个权重值检查，覆盖 S8/S16、两路在途、预取命中、取消、尾块和清除恢复。

生产参数 `SIZE=16, DATA_WIDTH=16` 的独立测量如下。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 994 | 365 |
| 寄存器 | 332 | 328 |
| DSP | 0 | 0 |
| RAMB36 | 0 | 64 |
| RAMB18 | 16 | 0 |
| 寄存器间最长组合单元数 | 7 | 5 |

该结构减少 629 个逻辑 LUT，增加 56 个 RAMB36 等效容量。生产器件为 `xc7a200tfbg484-3`；完整 SoC 的资源及实际组合级数使用整机报告统计。

## 重复执行

参考源代码来自提交 `cedf4ed3`。

```bash
mkdir -p build/kernel_row_storage_reference
git archive cedf4ed3 rtl/common rtl/npu/loaders/kernel_loader_buffer.sv | tar -x -C build/kernel_row_storage_reference
python3 test/kernel_row_storage/run_formal.py --source-root . --reference-root build/kernel_row_storage_reference --profiles 3:8 4:8 16:8 16:16 --out build/kernel_row_storage/formal
python3 test/kernel_row_storage/run_partitioned.py --source-root . --reference-root build/kernel_row_storage_reference --size 32 --width 16 --group-timeout 90 --out build/kernel_row_storage/partitioned_32_16
python3 test/kernel_row_storage/run_numeric.py --source-root . --reference-root build/kernel_row_storage_reference --out build/kernel_row_storage/numeric
python3 test/kernel_row_storage/run_four_state.py --source-root . --reference-root build/kernel_row_storage_reference --out build/kernel_row_storage/four_state
python3 scripts/fpga/open_fpga_synth.py --source-root . --case-config test/kernel_row_storage/synthesis_cases.json --cases kernel_buffer --out build/kernel_row_storage/synthesis --wide-alu-dsp-budget 740 --rtl-dsp-attributes --max-register-path-cells 10
```

`validation.json` 保存参数、已完成检查的数量、源代码散列、原报告路径和报告散列。详细逐周期输出与证明日志保存在测量目录。
