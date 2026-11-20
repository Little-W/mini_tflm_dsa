# IA 加载许可的组合深度优化

本项修改优化 `ia_loader_ctrl.sv` 的加载行数及加载许可判断，以及 `ia_loader.sv` 的外部 DMA 请求组合。参考提交为 `3c8cafeb2bb7029d903479ace4bd591e5109f03b`，保留配置、预取、缓存命中、取消和复位的逐周期行为。

## 当前实现

加载控制器分别计算普通组、尾组和已保存预取组的边界条件，再选择当前组的结果。配置值先转换为 `count_t`，再转换为 `LOAD_CNT_W`，与原有截断和扩展顺序一致。预取上界保持原有的 `LOAD_CNT_W` 位。

FPGA 分支对递增后的游标使用分组比较：第一组同时检查最低三个结果位；后续各组利用相邻低位确定的进位，检查两个结果位。各组独立计算并归约，生产配置中的七位游标使用两级 LUT 完成相等判断。通用和 ASIC 分支使用已有 `add_equal` 模块。比较覆盖模 `2^LOAD_CNT_W` 的回绕行为。

剩余请求条件同时检查游标小于组上界、已完成数量不等于组上界。三个目标分别完成比较，再选择当前组。槽号对应的忙碌位和有效位独立选择，最后与状态、加载器忙碌状态及剩余请求条件合并，生成 `can_start_load`。

IA 加载器先计算缓存资格和各模式的请求条件，将 `request_lookup_ready` 与 `ext_dma_start` 接入最终请求 LUT。授予逻辑单独合并查询就绪及对应资格，保持请求、授予和 DMA 启动处于原有周期。该实现不增加寄存器。

## 验证范围

`run_control.py` 从实际 RTL 提取组合逻辑，与参考源码中的关系式比较。它覆盖加载计数宽度 1、2、3、4、7、8、12，以及普通和 FPGA 两种实现；其中包含 `COUNT_WIDTH` 小于加载计数宽度的情况。请求比较将查询就绪、缓存资格、预取、忙碌、刷新、初始化和外部授予视为任意输入。共执行 16 组 SAT 证明。

`run_formal.py` 比较完整 IA 加载器、控制器和缓存管理器的公开输出及状态转移。八组参数包含实际 SoC、常规容量、32 位计数、64 个缓存块、SIZE=3、无序任务、BUS128 和 ASIC 配置。脚本不添加输入取值约束或复位顺序约束。异步复位经过 `async2sync` 转换，随后执行组合比较及两步归纳。八组参数共证明 134,803 个等价位。

数值验证通过官方 Xilinx LUT 与 DSP 功能模型运行实际加载器，并在每个有效时钟周期比较全部公开输出。两个测试分别覆盖有序预取以及 32 个物理缓存块的紧凑和普通格式加载，合计 180,122 个周期、903,952 次数值检查。预取测试执行 251 条命令，分组加载测试执行 81 个场景。

所有结果由 `collect_report.py` 核对源码、参考快照、原语模型、证明日志、数值结果及映射文件的 SHA-256 后写入 `measurement.json`。

## 实际 NPU 连接测量

测量保留完整 IA 控制器、加载器、前端及仲裁器之间的实际连接，显式设置 `ADDR_WIDTH=32`。展开后的维度计数为 29 位、加载游标为七位。数据计算模块、缓存存储模块和 DMA 数据传输模块作为接口边界；所有路径均从实际寄存器输出计算至寄存器数据、使能或复位端口。

采用相同物理面积代价的 LUT 库，ABC9 映射后验证真值关系。组合深度计入 LUT、MUXF 和 CARRY 单元，并按每个 LUT 输出的实际输入依赖计算。

| 测量项 | 参考设计 | 当前实现 |
|---|---:|---:|
| `cfg_ia_reuse_num` → 仲裁授予寄存器 | 15 | 11 |
| 加载游标 → 仲裁授予寄存器 | 14 | 11 |
| 请求坐标 → 仲裁授予寄存器 | 9 | 8 |
| 槽号 → 客户端未完成数量 | 10 | 11 |
| 所有 IA 寄存器 → 仲裁器寄存器 | 15 | 14 |
| 所有来源 → 仲裁授予寄存器 | 15 | 14 |
| 所有来源 → 客户端未完成数量 | 10 | 11 |
| 逻辑 LUT | 10,440 | 10,447 |
| 寄存器 | 7,881 | 7,881 |
| DSP48E1 | 34 | 34 |

资源数字对应上述连接测量范围。完整 SoC 的物理 LUT 位置和 150 MHz 时序由整机综合与布局流程核对。

## 重现

先加载本机 FPGA 工具链环境，再执行：

```bash
python test/ia_reuse_admission/run_control.py \
  --out build/ia_reuse_admission/control_final
python test/ia_reuse_admission/run_formal.py \
  --out build/ia_reuse_admission/formal_final
python test/ia_write_output_depth/run_numeric.py \
  --out build/ia_reuse_admission/numeric_final \
  --reference 3c8cafeb --cases interface --verilator verilator-modern
python test/ia_reuse_admission/run_joint.py \
  --out build/ia_reuse_admission/joint \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python test/ia_reuse_admission/collect_report.py \
  --current-map build/ia_reuse_admission/joint/current
```
