# 计算阵列、共享存储与 IA 普通 RTL 检查

本目录检查计算单元权重选择、阵列逐列控制、算术操作数选择、共享存储读取选择，以及 IA 请求和坐标控制。数据选择使用条件表达式、分组选择和布尔运算。计算单元保留两套权重寄存器，算术位宽、输入输出周期及更新优先级保持一致。

## 已完成的检查

`measurement.json` 对应 RTL 提交 `f0f83e1d`，参考提交为 `653477ed`，记录源码散列值、参数和运行结果。

| 检查 | 参数与范围 | 通过结果 |
|---|---|---:|
| 计算单元状态等价 | 5 组数据、权重和累加位宽，2 种权重装载模式 | 10 组配置，1,139 个比较位 |
| 计算单元四态仿真 | 未装载权重、未知数据位、连续交换和同时装载 | 100,000 周期，200,001 次比较 |
| `select_add` 全输入 SAT | 位宽 1、8、17、32、48 | 5 组配置，每组 3 个性质 |
| 共享读取选择全输入 SAT | 输入数量 5、7、8、9、16，以及扩展选择位宽 | 6 组配置 |
| 阵列整数参考计算 | 阵列规模 3、16，S8×S8、S16×S8、S16×S16 | 456 个场景，486,788 个数值 |
| IA 坐标等式全输入 SAT | 坐标位宽 8、32、35、40，低位分段 0、3、4、5 | 8 组配置 |
| IA 完整状态等价 | SoC、生产参数、32 位计数、64 块缓存、本地存储和 ASIC 宏 | 6 组配置，70,793 个比较位 |
| IA 全部公开输出逐周期比较 | 有序预取和分组计算，39 个输出 | 180,122 周期，903,952 个数值 |

阵列检查包含间断输入、不同流高度、权重交换、符号边界、INT32 回绕、部分和输入以及复位；测试程序启用未定义行为检查。IA 形式检查不限制源模块输入值。IA 接口检查在 FPGA 功能模型下同时执行参考实现和当前实现。

## 复现命令

工具环境需要 Python 的 `pyosys` 模块、Slang 前端、Yosys 及 Verilator。下列路径可替换为本机工具和输出目录。

```sh
python3 test/compute_rtl/run_cell_formal.py --reference 653477ed --out /tmp/compute_checks/cell
python3 test/compute_rtl/run_mux_formal.py --reference 653477ed --out /tmp/compute_checks/mux
python3 test/select_add/run_formal.py --out /tmp/compute_checks/select_add
python3 test/dip_array/run.py --sizes 3 16 --verilator verilator-modern --jobs 1 --out /tmp/compute_checks/array
python3 test/ia_arbiter_request/run_ia_formal.py --reference-rev 653477ed --out /tmp/compute_checks/ia_formal
python3 test/ia_write_output_depth/run_numeric.py --reference 653477ed --cases interface --out /tmp/compute_checks/ia_interface
```

资源和组合级数需要在固定器件参数下单独综合；数值检查和状态等价结果用于确认功能与周期行为。

## 共享读取选择资源

`shared_ram_read_mux` 采用二级二选一表达式完成组内选择。对七个 8,192 字节存储块的 `ia_ps_shared_ram` 独立综合，逻辑 LUT 从参考提交 `f0f83e1d` 的 4,440 降为 4,297，触发器保持 21 个，RAMB36 保持 14 个；全部组合路径最大 9 级，寄存器间最大 8 级。具体数据保存在 `shared_mux_measurement.json`。

选择器的 6 组全输入 SAT 检查全部通过。共享存储检查与 `test/ia_cache_selection/measurement.json` 使用同一份 RTL，完成 15,022,624 个数据数值比较。固定部分和通道使用 `ia_ps_channel_ram`；该模块分别综合计算资源。
