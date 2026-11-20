# 第 15 轮完整 SoC 综合与组合路径测量

本次测量固定源码提交 `3587da4318f0533f57ba43bb9ec787551debfb39`，源码树为 `bfaa433f98ddd9dc7115fa92f0688c16794fabef`，PicoRV32 子模块提交为 `ef203c2b0a3fb793280f5114941416c425c5b461`。生产设计包含权重预取寄存器、权重未完成数量、输出组分块数量、窗口描述符准备和前端配置及解码边界优化。

完整结果为 **54,344 个逻辑 LUT、2,444 个 RAM LUT、160 个 SRL、708 个 DSP48E1**。寄存器之间的最长组合路径为 **20 级**，当前仍需缩短至 15 级。所有 LUT 映射等价检查和本次选中 DSP 的官方模型证明均通过。

完整来源清单、参数、工具哈希、资源归属、150 组路径及形式证明结果保存在 [fpga_round15_measurement.json](data/fpga_round15_measurement.json)。

## 配置和资源

顶层为 `soc_top`，目标器件为 `xc7a200tfbg484-3`。NPU 使用 16×16 阵列、64 位总线、7 个 8 KiB 共享存储银行、4 KiB im2col 缓存、4 个 IA 缓存块和 16 个 PS 帧。CPU RAM 为 256 KiB，PS 使用原始 32 位表示。向量引擎、IS 模式、逐通道量化及各 AXI 时序缓冲均保留生产配置。

| 资源 | 数量 |
| --- | ---: |
| 逻辑 LUT 原语 | 54,344 |
| 分布式 RAM 所需 LUT 位置 | 2,444 |
| SRL 所需 LUT 位置 | 160 |
| 布局前名义 LUT 总数 | 56,948 |
| 触发器 | 47,070 |
| DSP48E1 | 708 |
| RAMB36E1 | 91 |
| RAMB18E1 | 30 |
| CARRY4 | 2,413 |

上述逻辑 LUT 按原语计数，`LUT6_2` 计为一个原语。RAM LUT 与 SRL 按其存储结构需要的位置数单独统计。本轮完成综合和技术映射，物理 LUT 位置数及布局布线后的 150 MHz 时序结果尚未测量。

按 RTL 来源分配的主要逻辑 LUT 如下。跨模块共享组合逻辑单独列出，详细文件保留全部来源及共享组合。

| 来源 | 逻辑 LUT |
| --- | ---: |
| `vector_engine.sv` | 6,118 |
| `vec_requant.sv` | 6,044 |
| `conv_im2col_frontend.sv` | 5,740 |
| 跨模块共享组合逻辑 | 5,092 |
| `conv_read_cache.sv` | 2,727 |
| `npu_top.sv` | 2,207 |
| `conv_next_use_predictor.sv` | 1,456 |
| `ia_loader_cache_mgr.sv` | 1,347 |
| `kernel_loader.sv` | 1,326 |
| `ia_loader_ctrl.sv` | 1,310 |

## 组合路径

连接图包含 216,136 个节点，全部节点均完成遍历。图中没有未分类原语或组合环。计数包含 LUT、进位单元、异步存储读取及 DSP 内部寄存边界之间的组合计算。对已证明的 `ONE48` 纯 ALU 模式，DSP 输出位只依赖可向该位传播进位的输入位。

导出的 150 组最长路径包含 3 组 20 级、13 组 19 级、30 组 18 级、46 组 17 级和 58 组 16 级。这里的数量描述所导出的路径组；完整最大深度由全部连接图计算。

| 起点与终点 | 级数 | 主要组合段 |
| --- | ---: | --- |
| 前端 `c[76]` → `state[1]` | 20 | `byte_high_one` 加法、坐标范围判断和状态选择 |
| `u_linear.rd_araddr_r[3]` → `rd_arlen_r[4]` | 20 | 读边界保护、读仲裁、`rd_accept_start` 和突发长度计算 |
| `u_kernel_loader.candidate_fields_q[115]` → 读 DMA 上下文存储 | 20 | 描述符比较、`load_fire`、传输长度计算与 DMA 字段选择 |
| 前端 `group_minus_two_q[0]` → `tap_wrap_q` | 18 | 末段判断、返回接收和后续坐标选择 |
| 向量引擎 `state[3]` → `reduce_acc[20]` | 18 | 累加输入选择和归约算术 |
| 前端状态 → IA 缓存写数据 | 18 | 返回数据选择和写入偏移处理 |
| 缓存 `demand_addr[8]` → `lookup_snapshot_valid` | 17 | 地址匹配、下一队首选择和元数据读取有效判断 |

第一条路径的起点还具有 `g_next_use.u_predictor.cfg[76]` 和 `bound_b[8]` 名称；这些名称对应同一条导线。该路径首先经过前端坐标计算中的四个 `CARRY4`，随后进入前端范围和状态选择。JSON 为每一级保留实际输入、输出连接和可用的 RTL 名称。

映射使用 6,667 ps 目标和 300 ps 连线成本。ABC 最后一次映射迭代的延迟估计为 10,576 ps。该数值来自映射成本模型，器件运行频率需在布局布线后的时序分析中测量。

## 验证

DSP 预算为 740，宽算术映射的最小位宽为 16，最多允许一个选中的组合 DSP 沿同一条组合路径连接。实际设计原有 430 个 DSP，另选取 278 个宽算术单元，总数为 708。

278 个选中单元覆盖 69 种输入、输出位宽与有符号参数组合。全部配置使用 Yosys 官方 `$alu` 和 `DSP48E1` 功能模型，对所有定义的输入证明 `X`、`Y` 和全部 `CO` 位一致。LUT 映射通过 ABC9 的网络等价检查。

DSP 按位依赖分析使用已通过官方模型证明的 48 个截断位置，`ALUMODE` 四个位均为自由输入。保存的证明与本轮测试文件、分析程序的 SHA256 完全一致。完整报告同时保存这些模型与工具哈希。

本轮展开、算术及存储综合、DSP 选取、LUT 前映射和最终 LUT 映射分别耗时 12.47、491.51、5.34、142.14 和 206.77 秒。最终映射阶段峰值进程树内存约 2.12 GiB。

## 重现命令

在上述固定源码及 PicoRV32 子模块提交上，使用报告中相同版本的 Pyosys、Slang 和 Xilinx 原语模型执行：

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --cases soc_top --out build/soc_round15_dsp740_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 16 \
  --wide-alu-maximum-chain 1

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_round15_dsp740_pre/soc_top \
  --out build/soc_round15_dsp740_cost/soc_top \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
  --max-lut-inputs 8

python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/soc_round15_dsp740_pre/soc_top/pre_alu.json \
  --selection build/soc_round15_dsp740_pre/soc_top/wide_alu_mapping.json \
  --top soc_top --out build/round15_selected_dsp_formal
```

路径分析使用 `scripts/fpga/netlist_metrics.py` 的 `connected_paths(module, limit=40, group_limit=150)`，并先通过 `register_origins(pre_lut)` 恢复寄存器原始信号名称。实际映射网表的 SHA256 为 `5dd408e43d69ecc19c3fd0d0c32f9fe1f8c1ec4e29b140983712b607a55a6e3d`。
