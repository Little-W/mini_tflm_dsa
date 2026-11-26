# 外部读取地址资格

`conv_guard_page_boundary` 按四个二位字段计算页内进位，输出完整突发是否位于同一 4 KiB 页。`conv_guard_read_valid` 将保存状态发出的请求与满足格式要求的直通请求并行归并，页边界结果只参与最后一级地址有效选择。

模块保持完整地址保护范围、AXI 突发格式检查、错误响应及握手时序。控制输入含未知值时使用完整状态选择表达式，保留四态传播。

## 实测结果

采用 32 位地址、64 位总线并启用 GEMM 页边界检查。其余源文件来自 `9bd6488c`，映射参数为 6667 ps 延迟目标、300 ps 连线成本和最多八个 LUT 输入。

| 项目 | 调整前 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 667 | 675 |
| 触发器 | 392 | 392 |
| DSP | 12 | 12 |
| 内部寄存器之间的最长组合单元数 | 10 | 10 |
| 输入地址及突发长度到 `m_arvalid` 的最长组合单元数 | 5 | 4 |

输入到输出的测量在输入和输出处添加仅用于分析的边界，真实 RTL 未增加寄存器或周期。完整网表连接图无缺失类型和组合环。实际器件频率由布局布线后的静态时序检查确定。

## 验证范围

- 16、32、33、40 位地址及 16、32、64、128、256 位总线，覆盖启用和关闭页边界拆分的七组配置；通用和综合模式共 14 项完整状态及公开输出等价证明通过。
- 32 位与 64 位总线、两种拆分配置，各完成 20,000 个四态周期，包含配置、复位、未知控制、响应停顿和边界地址。
- 实际 AXI 响应模型完成 10 条命令、46 次响应，其中两次为预期错误响应。
- ABC9 映射功能检查通过。

`measurement.json` 保存资源及路径，`validation.json` 保存各配置的验证结果。

```bash
python test/conv_guard/run_control_formal.py --reference-ref 9bd6488c \
  --out build/guard_read_qualification/generic
python test/conv_guard/run_control_formal.py --reference-ref 9bd6488c --fpga \
  --out build/guard_read_qualification/fpga
python test/conv_guard/run_four_state.py --reference-ref 9bd6488c \
  --out build/guard_read_qualification/four_state
python test/conv_guard/run.py
```
