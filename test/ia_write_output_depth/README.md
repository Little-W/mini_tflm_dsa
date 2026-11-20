# IA 紧凑字节算术与共享 RAM 写入控制

参考提交：`437a8d8117e21e263eea432d3b550b77622cb2c7`。
当前 RTL、依赖、形式证明和综合网表的 SHA256 保存在 [measurement.json](measurement.json)。

## 设计

`ia_loader_cache_mgr.sv` 通过已有 `select_add` 计算紧凑字节。写入数据低八位与提前生成的偏移相反数相加，结果按模 256 截断，与原始完整位宽减法的低八位相同。FPGA 分支每个输入通道使用一个组合 `DSP48E1`，生产配置共使用 8 个；所有 DSP 内部寄存器均旁路。通用及 ASIC 分支使用组合加法。

端口写使能从输入通道有效位和常量列区间生成。紧凑格式的第一端口覆盖整行，宽格式的两个端口分别覆盖前后八列。列移位补零、无效通道的数据值、字节掩码、地址、写入期间的复位行为和端口数据保持条件均保持原有逐周期关系。完整行读取、缓存容量及所有公开接口不变。

## 功能检查

| 检查 | 范围 | 结果 |
|---|---|---|
| 完整缓存等价证明 | 20 组参数与宏分支，57,078 个等价位，输入无约束 | 全部通过 |
| 生产实例完整等价证明 | 64 位总线、32 个缓存块、12 位 RAM 字地址、9 位紧凑偏移，2,696 个等价位 | 通过 |
| FPGA IA 全部公开输出比较 | 39 个公开输出，180,122 个周期，903,952 项数值检查 | 通过 |
| FPGA 共享 RAM | 7 × 8192 B，4,681,255 个周期，15,022,624 项数值检查，74,900,080 项逐周期检查 | 通过 |

形式检查覆盖 `XILINX_FPGA`、`SYNTHESIS`、`ASIC_SYNTHESIS` 的全部八种宏组合，以及 8、32、64、128、256 位总线、本地 RAM 和外部 RAM。功能模型直接读取工具链 Xilinx 原语库。

共享 RAM 检查包含每种分配方案的 256 个 INT8 偏移、宽格式方案的全部 65,536 种 INT16 位模式、1,280 种掩码、跨字写入和 IA/PS 同时访问。15 个 C++ 编译单元均启用未定义行为检查。Verilator 位宽检查对应用 RTL 保持开启；原语模型文件中的字符串扩展和未使用算术模式截断使用单独配置。

## 独立缓存映射

两份输入使用相同生产参数和工具依赖，仅缓存管理 RTL 不同。生产面积成本映射保留工具链的各输入引脚延迟，目标延迟参数为 6667 ps，布线估算参数为 300 ps。

| 资源 | 原生参考 | 原生当前 | 面积成本参考 | 面积成本当前 |
|---|---:|---:|---:|---:|
| 逻辑 LUT | 1,910 | 1,914 | 1,682 | 1,659 |
| LUTRAM 对应 LUT 位置 | 8 | 8 | 8 | 8 |
| 触发器 | 354 | 354 | 354 | 354 |
| DSP48E1 | 0 | 8 | 0 | 8 |
| CARRY4 | 88 | 72 | 88 | 70 |

| 实际连接路径 | 原生参考 | 原生当前 | 面积成本参考 | 面积成本当前 |
|---|---:|---:|---:|---:|
| 写数据输入到写数据寄存器 | 9 | 7 | 8 | 6 |
| 通道有效位到写使能寄存器 | 8 | 6 | 6 | 8 |
| 列位置到写使能寄存器 | 8 | 8 | 6 | 8 |
| 紧凑偏移到写数据寄存器 | 9 | 11 | 8 | 10 |
| 模块内部寄存器间最大路径 | 10 | 11 | 13 | 13 |

路径统计包含数据、使能和复位端口，沿实际逐位连接与 LUT 真值表计算。输入路径使用仅供分析的寄存器标记，资源表采用添加这些标记之前的网表。

## 实际 NPU 连接

联合映射保留 `npu_top` 中配置控制、帧调度、DMA、前端、预测器及 IA、kernel、bias 加载器之间的实际连接。计算阵列、向量计算、输出处理和共享数据 RAM 作为接口边界。面积成本映射复用同一份技术映射文件，并通过 ABC9 等价检查。

| 起点 | IA 写命令寄存器终点 | 原生级数 | 面积成本级数 |
|---|---|---:|---:|
| 窗口缓存 `response_queue_error[0]` | `ram_port_wr_data[174]` | 12 | 12 |
| 窗口缓存 `response_queue_error[0]` | `ram_port_wr_data[127]` | 13 | 13 |
| 窗口缓存 `response_queue_error[0]` | `ram_port_wr_en[0]` | 8 | 7 |
| 窗口缓存 `response_queue_error[0]` | `ram_port_wr_en[1]` | 12 | 12 |

两种联合映射中，8 个新增 DSP 的前后均没有其他未寄存 DSP。组合依赖检查在触发器和同步存储器处终止，并保留 LUT 每个输出的实际输入依赖。完整 SoC 的资源、面积成本映射路径及 740 个 DSP 总预算分配由整机测量确定；150 MHz 使用器件与布线延迟分析。

## 复现

在仓库根目录设置工具链环境后运行：

```bash
python3 test/ia_write_output_depth/run_formal.py \
  --reference 437a8d81 --out build/ia_write_output/formal_all
python3 test/ia_write_output_depth/run_numeric.py \
  --reference 437a8d81 --verilator verilator-modern --out build/ia_write_output/numeric
python3 test/ia_write_output_depth/prepare_measurement.py \
  --reference 437a8d81 --out build/ia_write_output/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ia_write_output/inputs/cases.json --cases reference current \
  --out build/ia_write_output/native \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 scripts/fpga/remap_fpga_luts.py \
  --source build/ia_write_output/native/reference --out build/ia_write_output/cost/reference \
  --mode physical-cost --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 scripts/fpga/remap_fpga_luts.py \
  --source build/ia_write_output/native/current --out build/ia_write_output/cost/current \
  --mode physical-cost --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/ia_write_output_depth/paths.py \
  --native build/ia_write_output/native --cost build/ia_write_output/cost \
  --out build/ia_write_output/paths.json
python3 test/frontend_ia_depth/ia_joint.py --reference 437a8d81 --cases current \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock \
  --out build/ia_write_output/joint
python3 test/ia_write_output_depth/joint_paths.py \
  --source build/ia_write_output/joint/current --out build/ia_write_output/joint_current_paths.json
python3 test/ia_write_output_depth/remap_joint.py \
  --source build/ia_write_output/joint/current --out build/ia_write_output/joint_cost/current \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/ia_write_output_depth/joint_paths.py \
  --source build/ia_write_output/joint_cost/current --out build/ia_write_output/joint_cost_paths.json
python3 test/ia_write_output_depth/collect_report.py \
  --build build/ia_write_output --out test/ia_write_output_depth/measurement.json
```
