# 前端通道控制与 IA 紧凑写入优化

参考提交：`47e51eff9831b42a36326cec6e074245ba0805d2`。当前三个 RTL 文件的 SHA256、形式证明、数值检查和联合映射结果保存在 [measurement.json](measurement.json)。

## 设计

`conv_next_use_predictor.sv` 在更新 `cfg_phase` 的同一时钟沿保存 `cfg_busy`。配置接收、配置拒绝、乘积溢出和配置完成均更新这一寄存状态，使用方直接读取配置忙标志。

`conv_im2col_frontend.sv` 使用 `add_equal` 并行判断通道增量与四个组内边界的关系。最多四个传输通道的配置提前计算每种通道数对应的组末关系，再由最后有效通道选择结果。宽通道配置使用 17 位加法等式检查器。下一通道索引的 16 位回绕和组末判断的 17 位回绕分别保持原有语义。

`ia_loader_cache_mgr.sv` 在列排列之前计算紧凑写入字节。数据先与零输入对应的紧凑字节进行异或编码，再按写入列移位，最后恢复对应字节。这样，移位补入的零和无效写入通道仍产生与完整 16 位输入、16 位偏移计算一致的数据值。宽格式数据、写掩码、地址和时钟周期关系保持一致。

## 功能检查

所有检查对应当前三个 RTL 文件的相同内容。

| 检查 | 覆盖范围 | 结果 |
|---|---|---|
| 通道范围与组末形式证明 | 通道数 1、2、3、4 的通用逻辑及官方 FPGA LUT 模型，共 8 组；宽通道组末的 49 个自由输入位，共 2 组 | 全部通过 |
| 完整预测器等价证明 | 1,989 个等价位 | 全部通过 |
| 预测器数值及周期比较 | 33 组配置，13,226 个向量，206,076 个周期，全部公开输出 | 全部通过 |
| FPGA 窗口 DMA | 接收 422 次请求，完成 418 次，复位取消 4 次；检查 4,457 个数据元素及 19 次预期错误响应 | 全部通过 |
| 窗口 DMA 连续传输周期比较 | 1,545 行周期记录 | 完全一致 |
| 非二次幂通道配置 | 30 组配置，960 次请求，7,916 个数据元素，249,411 行周期记录 | 数值与周期完全一致 |
| 完整 IA 缓存等价证明 | 5 组本地或外部 RAM 参数，32/64/128 位总线，13,862 个等价位 | 全部通过 |
| FPGA IA 接口比较 | 39 个公开输出，180,122 个周期，903,952 项数值检查 | 全部通过 |
| 7 × 8192 字节共享 RAM | 4,681,255 个周期，15,022,624 项数值检查，74,900,080 项逐周期数值检查 | 全部通过 |

形式证明不限制输入数据、偏移、通道有效位和配置取值。共享 RAM 检查覆盖生产配置的紧凑偏移、INT8 数据、全部 65,536 种 INT16 位模式、不同写入掩码、跨字写入及 IA/PS 同时访问。

## 前端、窗口队列、缓存和预测器联合映射

此范围采用实际 `axi_dual_block_dma` 描述符选择、窗口队列、完整前端、完整缓存和完整预测器。线性 DMA 与 AXI 读写保护模块作为接口边界。使用原生 `synth_xilinx` 和 ABC9，按实际逐位连接及各 LUT 输出真值统计路径。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 13,130 | 13,113 |
| LUTRAM 对应 LUT 位置 | 484 | 484 |
| 触发器 | 6,299 | 6,300 |
| DSP48E1 | 46 | 46 |
| RAMB18E1 | 20 | 20 |
| CARRY4 | 1,118 | 1,118 |
| 完整范围的最长寄存器间路径 | 16 | 16 |
| 预测器配置状态到 `tap_wrap_q` | 15 | 14 |
| 预测器配置状态到 `tap0` | 13 | 13 |
| 预测器配置状态到 `incoming_word` 输入寄存器 | 13 | 11 |
| `active_remaining` 到 `group_range_q` | 13 | 14 |
| `active_remaining` 到 `state` | 13 | 14 |

当前完整范围有三组 16 级路径：缓存 `fg_state[1]` 到 `row_wrap_q`，`pf_distance_q[0]` 到 `pf0_y[1]`，以及预测器 DSP 内部寄存器到 `coordinate_good_s1`。这些完整范围结果与表中指定路径一起保存在测量文件中。

## IA 写入的实际 NPU 连接映射

此范围保留 `npu_top` 中的配置控制、帧调度、DMA、前端、预测器、IA、kernel 和 bias 加载器之间的实际连接。计算阵列、向量计算、输出处理及共享数据 RAM 作为接口边界。两份输入仅在 `ia_loader_cache_mgr.sv` 上存在变化，IA 参数包含 64 位总线、32 个缓存块及 12 位共享 RAM 字地址。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 32,881 | 32,754 |
| LUTRAM 对应 LUT 位置 | 1,216 | 1,216 |
| 触发器 | 18,683 | 18,683 |
| CARRY4 | 2,454 | 2,440 |
| DSP48E1 | 81 | 81 |
| RAMB18E1 / RAMB36E1 | 20 / 1 | 20 / 1 |
| 前端 `state[4]` 到所有 IA 写数据寄存器 | 17 | 17 |
| 前端 `state[4]` 到 IA 写数据第 140 位 | 13 | 13 |
| 前端 `state[4]` 到 IA 写数据第 148 位 | 14 | 12 |
| 前端寄存器到所有 IA 写数据寄存器 | 18 | 18 |
| 前端寄存器到 IA 写掩码寄存器 | 15 | 16 |
| 前端寄存器到 IA 写使能寄存器 | 17 | 18 |

IA 路径表统计所列起点与终点之间的连接。前端与 IA 两个独立映射的逻辑 LUT 分别减少 17 个和 127 个。完整 SoC 的 LUT 数量与最长路径采用整机 DSP 分配及全局映射结果；150 MHz 时序采用目标器件的单元和布线延时分析。

## 复现

在仓库根目录设置工具链环境后运行：

```bash
python3 test/frontend_ia_depth/formal.py \
  --reference 47e51eff --out build/r19_depth/frontend_formal
python3 test/conv_replacement/predictor_test.py \
  --reference-ref 47e51eff --verilator verilator-modern \
  --build build/r19_depth/predictor_numeric --out build/r19_depth/predictor_numeric/summary.json
python3 test/window_dma/run.py --reference-ref 47e51eff --fpga \
  --verilator verilator-modern --jobs 1 --out build/r19_depth/window_fpga
python3 test/frontend_ia_depth/window_boundary.py --model build/r19_depth/window_fpga \
  --proof build/r19_depth/frontend_formal/summary.json \
  --verilator-include "$(verilator-modern --getenv VERILATOR_ROOT)/include" \
  --out build/r19_depth/window_boundary
python3 test/ia_write_layout/run_formal.py \
  --reference-ref 47e51eff --out build/r19_depth/ia_formal
python3 test/ia_write_admission/run_interface.py --reference-rev 47e51eff \
  --verilator verilator-modern --out build/r19_depth/ia_interface
python3 test/ia_shared/run.py --bank-bytes 8192 --bank-count 7 \
  --compact-offset-width 9 --jobs 1 --verilator verilator-modern --out build/r19_depth/ia_shared
flock /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock \
  python3 test/window_descriptor_stage/synthesis.py --reference 47e51eff \
  --include-cache --include-predictor --out build/r19_depth/frontend_joint
python3 test/frontend_ia_depth/frontend_paths.py --joint build/r19_depth/frontend_joint \
  --out build/r19_depth/frontend_paths.json
python3 test/frontend_ia_depth/ia_joint.py --reference 47e51eff \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock --out build/r19_depth/ia_joint
python3 test/frontend_ia_depth/ia_paths.py --joint build/r19_depth/ia_joint \
  --out build/r19_depth/ia_exact_paths.json
python3 test/frontend_ia_depth/summarize.py --build build/r19_depth \
  --out test/frontend_ia_depth/measurement.json
```
