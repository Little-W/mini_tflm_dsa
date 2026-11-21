# 调度器游标范围保存

`ps_window_scheduler` 将可扫描的帧范围保存在 `cursor_mask`。复位、配置接收、压力处理和命令完成均在原有状态更新边沿更新该掩码。候选帧资格直接合并 `live`、`frame_open` 与保存的范围；命令接收、错误通知和预测输出的周期保持一致。

## 验证

完整状态证明覆盖六组 `SIZE / FRAME_COUNT / MAX_REUSE_TILES` 参数，共 20,652 个状态与输出位。参考模型额外导出 `cursor_mask[i] == (i >= cursor)`，并将这一对应关系纳入归纳证明。全部外部输入保持未约束，所有匹配的存储、状态及输出目标均通过检查。

八组 FPGA 与 ASIC 四态逐周期检查完成 768 个配置、666,384 次公开输出比较，以及 228,992 个含四态输入的执行周期。测试包含命令接收、压力处理、完成、复位、配置位 X/Z 和控制位 X/Z。

生产参数 `SIZE=16, FRAME_COUNT=16, MAX_REUSE_TILES=32` 的独立测量如下。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,111 | 1,128 |
| 包含分布式存储的名义 LUT | 1,167 | 1,184 |
| 寄存器 | 901 | 912 |
| DSP | 13 | 13 |
| RAMB36 | 2 | 2 |
| 寄存器间最长组合单元数 | 9 | 9 |

该修改处理完整 SoC 中游标经过范围比较、优先编码与元数据读取的组合路径。独立测量使用完整连接图；完整 SoC 中的实际级数由后续整机测量确认。150 MHz 的频率检查仍使用目标器件实现后的时序报告。

## 重复执行

参考源代码来自提交 `cedf4ed3`。

```bash
mkdir -p build/scheduler_cursor_reference
git archive cedf4ed3 rtl/common rtl/npu/control/ps_window_scheduler.sv | tar -x -C build/scheduler_cursor_reference
python3 test/scheduler_cursor/run_formal.py --source-root . --reference-root build/scheduler_cursor_reference --module ps_window_scheduler --profiles 4:1:1 4:3:5 4:4:0 16:16:32 16:16:0 16:33:64 --fpga --out build/scheduler_cursor/formal
python3 test/scheduler_command_outputs/run_four_state.py --source-root . --reference-root build/scheduler_cursor_reference --profiles 4:2:0 8:4:1 16:8:16 16:16:32 --out build/scheduler_cursor/four_state
python3 scripts/fpga/open_fpga_synth.py --source-root . --case-config test/scheduler_cursor/synthesis_cases.json --cases scheduler --out build/scheduler_cursor/synthesis --wide-alu-dsp-budget 740 --rtl-dsp-attributes --max-register-path-cells 10
```

`validation.json` 保存源代码散列、参数、通过数量、原报告路径和报告散列。
