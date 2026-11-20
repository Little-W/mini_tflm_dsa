# NPU 总线故障处理与配置接收

`npu_top` 启用 `axi_block_dma_arbiter.p_register_bus_error`。DMA 在错误响应握手的当前周期停止新命令并排空已接收事务，向顶层报告的 `dma_bus_error` 保存一个周期。顶层在 `task_fault` 有效期间停止接收配置，内部 `cfg_start_event` 与公开的 `calc_start && sa_ready` 握手使用相同条件。

## 配置接收逻辑证明

```sh
python3 test/npu_registered_fault/run_formal.py --out build/npu_fault_formal
```

脚本从实际 `npu_top.sv` 提取配置接收逻辑。FPGA 和 ASIC 两种配置均使用无输入约束的 SAT 检查，覆盖就绪条件、配置接收和故障期间的请求抑制。

## 完整 NPU 验证

```sh
python3 test/npu_registered_fault/run.py \
  --out build/npu_registered_fault --verilator verilator --jobs 1
```

完整测试使用生产参数与 FPGA 原语功能模型，检查卷积、矩阵运算、INT8/INT16 输出、两种数据流、PS 容量、帧输出和错误恢复。逐周期检查包括：

- 错误报告与上一周期的实际 DMA 错误事件一致。
- 故障期间不接收新配置。
- 内部配置接收条件与公开请求握手一致。
- 正常完成时没有尚未报告的总线错误。
- R 通道错误和 B 通道错误均实际发生，并完成错误恢复后的任务。

同一次执行还检查计算输出寄存周期、量化整组预留、权重提交、帧地址以及全部任务的数值结果。报告保存输入文件指纹、仿真程序构建记录和各类检查次数。
