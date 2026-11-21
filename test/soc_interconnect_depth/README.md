# SoC AXI 互连组合条件

互连分别计算 RAM 当前所有者的结束资格和新所有者的启动资格。CPU 正在接收 RAM 最后一个响应时，当前事务的结束条件直接使用已知 RAM 所有权；从其他目标切换到 RAM 时，只检查对应 MMIO 响应。仲裁优先级、未完成事务计数、地址与响应握手及公开输出周期保持不变。

## 验证结果

8 组参数证明原有状态和全部公开输出逐周期一致，共 5,628 个比较位。公开输入没有数值或握手限制。参数覆盖 32、40、64 位地址，32、64 位数据，1、1,031、65,536、524,288 个 CPU 存储字，非零地址起点、重叠译码区域和不同未完成事务数量。

四态测试使用 20,001 个周期比较 73 个公开输出和关键读事务状态，包含复位、任意有效与就绪组合，以及输入中的 X 和 Z。Icarus 仿真将枚举类型表示为相同位宽的逻辑类型和同值常量，所有表达式与时序块保持不变。

参考提交为 `aa0a169c7d4a514523e2fb50b5037bdca42c7340`。结果与实际源码 SHA-256 保存在 [measurement.json](measurement.json)。

## 局部映射

测量完整 `soc_axi_interconnect`，参数为 32 位地址、64 位数据、65,536 个 CPU 存储字，读写各允许 4 个未完成事务。两份实现使用相同参数，组合图均完整。

| 指标 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 576 | 584 |
| 触发器 | 156 | 156 |
| 最长内部寄存器间路径 | 10 级 | 10 级 |
| `m_ram_rvalid` 输入至 `ram_rd_active_q` | 8 级 | 3 级 |

输入边界路径用于定位与 RAM 响应缓冲连接后的组合级数，单独列出。完整 SoC 的寄存器间最大级数需使用整机映射结果；150 MHz 需检查布局布线后的时序报告。

## 复现

在仓库根目录执行，需要 `pyosys` 和 Icarus Verilog：

```bash
python test/soc_interconnect_depth/run_formal.py \
  --reference-ref aa0a169c --out build/soc_interconnect_depth/formal
python test/soc_interconnect_depth/check_four_state.py \
  --reference-ref aa0a169c --out build/soc_interconnect_depth/four_state
python test/soc_interconnect_depth/prepare_measurement.py \
  --formal build/soc_interconnect_depth/formal \
  --out build/soc_interconnect_depth/cases.json
python scripts/fpga/open_fpga_synth.py \
  --case-config build/soc_interconnect_depth/cases.json \
  --cases reference current --max-register-path-cells 14 \
  --out build/soc_interconnect_depth/mapping \
  --lock-file /tmp/npu_synthesis_20261121.lock
python test/soc_interconnect_depth/collect_report.py \
  --formal build/soc_interconnect_depth/formal \
  --four-state build/soc_interconnect_depth/four_state \
  --reference-mapping build/soc_interconnect_depth/mapping/reference \
  --mapping build/soc_interconnect_depth/mapping/current \
  --out build/soc_interconnect_depth/measurement.json
```
