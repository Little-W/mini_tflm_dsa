# IA 请求比较与 DMA 客户端计数

本目录记录 `rtl/npu/loaders/ia_loader.sv` 与 `rtl/npu/dma/axi_block_dma_arbiter.sv` 的实现、验证及联合映射结果。参考版本为 `437a8d8117e21e263eea432d3b550b77622cb2c7`。完整参数、源码 SHA256、数值测试结果、映射输入与组合路径保存在 [measurement.json](measurement.json)。

## RTL 结构

`ia_ordered_coordinate_equal` 判断固定宽度加法结果的高位是否与目标坐标相等。生产参数使用 32 位操作数和 4 位低位截取，运算保持 32 位加法的溢出行为。最低两位先产生进位；第 2、3 位与目标高位所要求的进位共同形成首个高位等式。其余高位根据本位与相邻低位的加法关系并行比较，按六个条件一组归约，首个高位等式直接进入最终归约。其他位宽和 ASIC 参数使用通用加法等式实现。

有序请求的行数和槽位分别按三对位一组比较。有效标志与这些比较结果先完成归约，两个坐标等式在末级合并得到 `request_lookup_ready`。`request_lookup_match` 保持坐标与行数的比较语义。槽位、行数及有效标志的组合级数因此独立于坐标等式的到达时间。新实例使用明确宽度的中间信号，新增注释采用中文。

五个 DMA 客户端分别使用自己的 `start && granted` 接收事件，独立更新两位在途计数。完成和取消条件继续使用原有响应标记及命令标记。FPGA 实现将每个计数的两个下一状态位放入同一个 `LUT6_2`，通用实现使用相同的更新表。计数按两位宽度计算，复位值为零，命令接收和完成的周期保持一致。

| 接收、完成、取消 | 计数变化 |
| --- | ---: |
| `100` | +1 |
| `001`、`010`、`111` | −1 |
| `011` | −2 |
| `000`、`101`、`110` | 0 |

## 联合映射

测量保留 `npu_top` 中 IA 与仲裁器的实际连接。控制器、缓存管理、DMA、计算阵列和其他加载器的接口作为分析边界，完整模块名单位于报告的 `interface_boundaries` 与 `manifest.boundaries`。`request_p0` 的 32 位、`request_q0` 的 32 位和 `tl_slot_id` 的 6 位全部保留为独立分析起点。

`request_p0` 直接连接 `load_cursor_p0` 寄存器，`tl_slot_id` 直接连接 `tl_slot_id_r` 寄存器；Q 坐标统计覆盖控制器输出端口之后的组合逻辑。分析起点所用的寄存器模型仅用于路径计算，资源统计来自加入这些模型之前的映射网表。

映射采用相同的 Xilinx 原语库与 `physical-cost` LUT 成本，延迟目标为 6,667 ps，连线估计为 300 ps，允许最多八个 LUT 输入。参考与当前网表均通过 `ABC9 &verify`。所有路径图完整，并检查寄存器的数据输入和控制输入。

| 组合路径范围 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| `request_p0` → `rd_grant_client` | 16 | 9 |
| `request_q0` 端口 → `rd_grant_client` | 16 | 9 |
| `tl_slot_id_r` → 任意客户端在途计数 | 12 | 10 |
| `tl_slot_id_r` → DW 在途计数 | 12 | 无组合依赖 |
| IA 范围内任意起点 → 仲裁器状态 | 16 | 13 |
| 分析范围内任意起点 → `rd_grant_client` | 16 | 13 |
| 分析范围内任意起点 → 客户端在途计数 | 13 | 10 |

级数按 LUT、CARRY 和 MUX 等组合单元计数。当前上述相关路径的最大值为 13，满足本次局部测量不超过 15 的要求。

| 资源 | 参考版本 | 当前实现 | 变化 |
| --- | ---: | ---: | ---: |
| 逻辑 LUT 原语 | 8,850 | 8,793 | −57 |
| LUT RAM 所需位置 | 276 | 276 | 0 |
| 触发器 | 6,924 | 6,924 | 0 |
| CARRY4 | 615 | 611 | −4 |
| DSP48E1 | 34 | 34 | 0 |

这些资源数对应上述联合测量范围。整机资源由完整 SoC 综合及物理布局结果统计；150 MHz 由完整布局布线的时序报告确认。

## 功能验证

### 形式等价

坐标比较器使用八组位宽及实现参数进行无输入约束 SAT 比较，覆盖 8、32、35、40 位操作数，0、3、4、5 位低位截取，以及 FPGA 和通用实现。

完整 IA 加载器使用相同状态起点比较所有状态转移和公开输出，六组参数共完成 **70,227 个等价比较位**。输入数据、配置及请求均保持自由取值。

| 参数组 | 等价比较位 | 结果 |
| --- | ---: | --- |
| `soc` | 11,793 | 通过 |
| `production` | 11,781 | 通过 |
| `full_count` | 11,826 | 通过 |
| `large_cache` | 16,892 | 通过 |
| `local_size3` | 6,153 | 通过 |
| `asic` | 11,782 | 通过 |

其中 `soc` 使用实际 SoC 的 12 位 RAM 地址与 16 个 PS 帧参数，`production` 使用默认 RAM 地址参数，`full_count` 使用 32 位计数，`large_cache` 使用 64 个缓存块，`local_size3` 使用 SIZE=3、BUS32、内部 RAM，`asic` 使用 ASIC 参数。

完整仲裁器进行七组比较，覆盖 BUS32、BUS64、BUS128 与量化客户端开关的六种组合，以及 ASIC BUS64。共完成 **15,549 个等价比较位**。五个客户端的全部十个计数状态位设为明确的比较输出；DMA 的所有输出作为共同的自由输入，送往 DMA 的所有端口参与比较。

### 数值与周期比较

| 检查 | 完成情况 |
| --- | --- |
| 有序预取 | 57,835 周期，251 条命令，179,920 次数值检查 |
| 分组缓存复用 | 122,287 周期，81 个场景，724,032 次数值检查 |
| IA 全部公开输出 | 合计 180,122 周期，与参考版本逐周期相同 |
| 完整 DMA BUS32、BUS64 | 每组 21 个场景、905 次检查 |
| DMA 取消与并发 | 每组覆盖 15 次取消、5 次同拍释放、5 次授予撤销、8 次上下文占满检查；最短命令接收间隔为 2 周期 |
| 窗口 DMA | 接收 422 条、完成 418 条、复位取消 4 条，检查 4,457 个数据元素与 19 次错误响应 |
| 连续窗口访问 | 1,545 个周期的逐周期记录与参考版本相同 |

FPGA 数值测试使用工具链提供的原语功能模型。`test/ia_request_lut/models.py` 提供 `LUT3`、`LUT6` 和 `LUT6_2` 的官方模型。IA 和 DMA 数值测试同时检查 C++ 未定义行为。

## 复现

在仓库根目录启用项目工具链后运行：

```bash
python test/ia_arbiter_request/run_ia_formal.py \
  --reference-rev 437a8d81 --out build/ia_arbiter_request/ia_parallel_verified
python test/ia_arbiter_request/run_arbiter_formal.py \
  --reference-rev 437a8d81 --out build/ia_arbiter_request/arbiter_verified
python test/ia_write_admission/run_interface.py \
  --reference-rev 437a8d81 --verilator verilator-modern \
  --out build/ia_arbiter_request/ia_cycle_verified
python test/dma_read_permission/run_numeric.py \
  --verilator verilator-modern --out build/ia_arbiter_request/dma_verified
python test/window_dma/run.py --fpga --reference-ref 437a8d81 \
  --verilator verilator-modern --out build/ia_arbiter_request/window_verified
python test/ia_arbiter_request/run_joint.py --reference 437a8d81 \
  --control-boundary --out build/ia_arbiter_request/joint_final \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python test/ia_arbiter_request/collect_report.py
```

`collect_report.py` 校验源码、官方原语模型、参考版本、证明日志、数值测试明细、映射输入和 LUT 库的哈希；同时确认所有坐标与槽位位数均保留，并检查所需路径存在及组合级数上限，随后保存 `measurement.json`。
