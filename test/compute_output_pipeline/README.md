# 计算输出流水检查

`compute_core` 在最终输出增加一级寄存。每行的 `acc_data_out`、`acc_data_valid` 和 `tile_calc_over` 同时经过该阶段，乘加与偏置加法分别位于两个时钟周期。

```mermaid
flowchart LR
    A["PE 输入寄存器"] --> B["乘加运算"] --> C["acc_data_out 寄存器"] --> D["偏置加法"] --> E["量化输入行缓存"]
```

数据寄存器每拍采样，不需要复位。`rst_n` 异步清零有效标志、tile 完成标志和最终分组完成标志，复位期间的数据不会被量化单元接收。

## 控制时序

| 信号或操作 | 相对于阵列最终行的时序 |
|---|---|
| 最终结果和有效标志 | 延迟一个周期 |
| 最终 tile 完成标志 | 随数据延迟一个周期 |
| 最终分组完成事件 | 延迟一个周期，保留 `final_output_overlap` 的控制关系 |
| 中间分组完成事件 | 保持原周期 |
| PS 存储写回及重放 | 保持原周期 |

重叠模式允许在最后一行进入量化输入缓存的同周期报告最终分组完成。非重叠模式在该行接收后的下一周期报告完成，使控制器读取更新后的偏置和量化参数就绪状态。IS 偏置行号由寄存后的 `acc_data_valid` 推进，预读出的下一行偏置与下一行数据对应。

顶层直接输出预留计入这一计算输出周期。`SIZE=16` 时需要的额外输出银行数量为 2。量化分时模式在启动分组时预留全部行，预留范围包含尚未到达缓存的计算输出；其行缓存仍保持 512 行、每行 513 位。

## 验证结果

结果及源码 SHA-256 保存在 `measurement.json`，完整事务比较保存在 `transactions.json`。

| 检查 | 参数与覆盖范围 | 结果 |
|---|---|---:|
| 输出与分组完成的无界归纳 | `SIZE=1/2/3/4/16/32`；实际 RTL 抽取；PS 输出为任意二态数据和控制；只约束首周期复位 | 6 组通过 |
| 实际计算核心比较 | `SIZE=2/3/4/16`，S16×S16；每组 4,096 周期，含权重提交、间断输入、复位、两种重叠模式和 PS 重放 | 102,450 个数据值通过 |
| 四态输出寄存检查 | X/Z 数据与有效标志、异步复位 | 4,096 周期，12,288 个数据值通过 |
| 完整生产 NPU | 16×16 阵列、64 位总线、7×8,192 字节共享存储；卷积、矩阵、IS/WS、S8/S16、参数装载、错误恢复、容量及输出暂停 | 86 项事务通过，216,348 次 INT32 检查 |
| 完整 NPU 输出阶段观察 | 每拍核对数据、有效标志、tile 完成、最终和中间分组完成 | 17,360 行，277,760 个数据值通过 |
| 量化初始化边界 | `exec_init_requant` 时检查原始最终行和输出寄存均无有效数据 | 674 次通过 |

完整事务使用相同的输入、配置、INT32 参考值和目的内存参考内容。错误码保持一致，成功事务的 INT32 检查数量和写出字节数量一致。参考运行累计 961,873 周期，当前运行累计 963,179 周期，增加 1,306 周期；单项事务增加 0～583 周期。报告允许新增的内部流水周期，并逐项记录任务执行周期。

上述检查覆盖 RTL 功能与周期关系。目标器件上的组合路径和 150 MHz 时序由 Vivado 实际综合、布局布线及时序报告确认。

## 运行命令

需要 Python、带 Slang 的 `pyosys`、Verilator 和 Icarus Verilog。输出目录可以替换为本机路径。

```sh
python3 test/compute_output_pipeline/run_formal.py --out /tmp/compute_output/formal
python3 test/compute_output_pipeline/run.py --out /tmp/compute_output/behavior --verilator verilator-modern
python3 test/compute_output_pipeline/run_four_state.py --out /tmp/compute_output/four_state
python3 test/compute_output_pipeline/run_npu.py --out /tmp/compute_output/npu --verilator verilator-modern --jobs 1
python3 test/compute_output_pipeline/compare_transactions.py \
  --reference-report /tmp/reference_npu/summary.json \
  --current-report /tmp/compute_output/npu/suite/summary.json \
  --out /tmp/compute_output/npu/comparison.json
```

`run.py` 使用参考提交 `9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a` 的实际计算核心。形式检查从参考与当前源文件提取输出控制及元数据，将 PS 输出作为验证输入。完整 NPU 检查运行真实 FPGA 分支和官方 DSP 功能模型，同时保留已有容量、权重、参数和总线检查。
