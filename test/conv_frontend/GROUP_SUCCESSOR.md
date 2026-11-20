# 归约组末偏移与坐标边界

前端接收描述符时，将 `tile_q0 + c.group_c` 保存为 33 位的 `next_group_q`。配置接收时依据新组宽度更新该值，复位时清零。加法保留进位，以覆盖全部 32 位归约偏移及 16 位组宽度。

快速请求条件比较 `tile_q0` 是否等于 `q0` 或 `next_group_q`。预计算使用已有的描述符及配置接收边沿，公开接口的延迟、有效状态、数据和错误响应保持相同周期。

输出列和卷积核列的循环判断直接使用配置阶段保存的末列值。几何尺寸为零时，循环条件保持无效。输入坐标按高位和低十六位分别检查：高位非零表示坐标超出十六位图像范围，低位再与图像宽高比较。

## 验证

状态关系 `next_group_q == {1'b0, q0} + 33'(c.group_c)` 已通过 SAT 时间归纳证明，包含复位、配置优先、有效描述符接收以及保持状态。输入位宽范围不受额外限制。测试从实际 RTL 提取更新表达式和比较表达式；坐标及末列判断另作全部输入编码的 SAT 比较，再逐字核对模块其余内容。

前端公开输出逐周期比较覆盖四组参数，每组包含 37 项数值任务，共 1,665,234 个周期；另有 23 项控制检查和 134 个周期。包括 32 位、64 位 AXI，总线等待、输出暂停、窗口预取及配置错误处理。

```sh
python3 test/conv_frontend/tools/group_successor_equivalence.py --out build/frontend_q0/formal
python3 test/conv_frontend/tools/compare_frontend.py --reference-ref 0ee8d2b --out build/frontend_q0/compare
python3 test/conv_frontend/tools/synthesis.py --out build/frontend_q0/synthesis
python3 test/conv_frontend/tools/measure_group_successor.py --mapped build/frontend_q0/synthesis/mapped.json --pre-lut build/frontend_q0/synthesis/pre_lut.il --out build/frontend_q0/metrics.json
```

## 独立 FPGA 综合

配置为 `SIZE=16`、64 位 AXI，缓存和预测器保留为模块边界。下表记录提交 `116a889` 的独立测量，该前端源码也包含于 `05be5b8`。后续配置边界和位置解码的时序结果见 [STREAM_TIMING.md](STREAM_TIMING.md)。

| 项目 | 比较版本 `975ce61` | 预计算版本 `116a889` |
|---|---:|---:|
| 逻辑 LUT | 6,600 | 6,455 |
| 触发器 | 3,164 | 3,197 |
| DSP48E1 | 30 | 30 |
| CARRY4 | 710 | 715 |
| 从 `q0` 出发的最长组合单元数 | 23 | 15 |
| 从 `q0` 到状态寄存器的最长组合单元数 | 19 | 15 |
| 从 `next_group_q` 到状态寄存器的最长组合单元数 | 不适用 | 10 |
| 模块内部最长组合单元数 | 25 | 22 |

路径统计使用实际网表连接关系及原寄存器名称，仅筛选起点，保留所有组合边和接收寄存器。完整结果见 `docs/data/frontend_group_successor_validation.json`。150 MHz 目标由完整器件布局布线时序报告检查。
