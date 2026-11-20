# 前端接收步长与进位选择

参考提交为 `9846295cbfb14945f0b55a54f4abf99ee7c854c0`。
当前前端源码 SHA256 为 `f28f9a378a219b5c4860097edd494e68b2333d90112e52a5b39ba96dc44eb358`。
生产修改仅涉及 `rtl/npu/conv/conv_im2col_frontend.sv`。

## 当前设计

既有描述符比较将 `tile_q0` 与 `q0` 分为两个等值分组，分别覆盖低十八位和高十四位。两个分组结果直接参与每个步长位的选择。位置相同时，`incoming_delta` 为零；其他位置按照 `incoming_tap_wrap` 选择对应的完整 32 位字节步长。

两种步长的低两位加法仍并行计算。其进位使用相同的五输入选择函数，与步长高位同时进入两个三十位数据字等式。每个选择由一个 LUT6 实现，五个有效输入为两个等值分组、步长选择及两种数据位，`INIT` 为 `64'h00ac_acac_00ac_acac`。通用实现保留等价的条件表达式。

寄存器、状态更新、接口周期、复位、配置与存储容量保持一致。所有位模式均保留，包括步长最高位、地址回绕以及无效周期的组合输出。

## 形式与窗口验证

`formal.py` 提取实际源码，在 322 个无约束输入位上比较完整 32 位 `incoming_delta`、低位进位、两个字等式和原描述符比较输出，共 39 位。通用逻辑与官方 FPGA LUT 模型均通过；两个查找表的共 128 项真值也全部通过。脚本同时确认其他生产源码内容保持一致。

实际状态表达式比较覆盖 828 个无约束输入位及 8 个输出位，包括全部五个状态位、两个字等式和字命中结果。完整 `begin`、`if`、`case` 优先级以及空分支均从生产状态过程提取，复位与无效状态也参与比较。此项通过，原状态更新语句保持一致。

官方 FPGA 窗口模型使用 `SIZE=16`、四个通道、四项未完成请求和完整 4 KiB 缓存。参考与当前模型的 422 次请求接收、418 次完成、4 次复位取消、4,457 个数据检查及 19 项错误检查一致。连续驻留场景完成 512 次响应、2,048 个元素，耗时 1,534 周期，最大响应间隔为 3；保存的 1,545 行逐周期记录逐字节相同。测试覆盖随机坐标、背压、窗口与普通 DMA 并发、授予撤销、配置等待、非法描述符、总线错误恢复和复位。

## 局部映射

测量包含实际 DMA 描述符字段选择、完整组内范围和快速接收比较、步长与进位、两个字等式、实际就绪逻辑以及前端完整状态更新表达式。其他条件在 `measurement.json` 列出的寄存输入处形成测量边界。参数为 `SIZE=16`、`LANES=4`、`TILE_COUNT_W=5`、`CACHE_POLICY=3`。

两组测量均采用 `physical-cost`、最大六输入 LUT 和 6,667 ps 目标值。LUT 数为映射逻辑单元数，完整 SoC 物理 LUT 位置另由布局统计。

| 连线参数 | 逻辑 LUT，参考→当前 | 全部最长组合路径 | `win_busy`→状态 | `win_busy`→实时字等式 | `win_busy`→字命中 |
|---|---:|---:|---:|---:|---:|
| 700 ps | 523→535 | 14→13 | 14→13 | 8→7 | 10→9 |
| 300 ps | 514→517 | 14→12 | 14→12 | 8→7 | 9→8 |

两组的测量寄存器均为 836 个，CARRY4 为 19→20，DSP 与存储原语均为零。全部 ABC9 映射等价检查及组合路径图完整性检查通过。已映射网络中，`win_busy` 至 `incoming_delta[31:2]` 的组合段均为 5→4 级；此项终点为内部组合信号。完整 SoC 的寄存器路径由整机映射独立计算。

## 重现

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python test/frontend_delta_select/formal.py \
  --out build/frontend_delta_select/final/formal
python test/frontend_delta_select/synthesis.py \
  --proof build/frontend_delta_select/final/formal/summary.json \
  --out build/frontend_delta_select/final/local \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock \
  --max-lut-inputs 6 --wire-delays 700 300
python test/frontend_delta_select/segments.py \
  --local build/frontend_delta_select/final/local
python test/frontend_incoming_depth/window.py \
  --proof build/frontend_delta_select/final/formal/summary.json \
  --out build/frontend_delta_select/final/window \
  --verilator verilator-modern
python test/frontend_delta_select/collect_report.py \
  --build build/frontend_delta_select/final \
  --out test/frontend_delta_select/measurement.json
```

正式结果和源码摘要保存在 `measurement.json`；原始证明日志、映射网络、路径及窗口记录保存在 `build/frontend_delta_select/final/`。
