# 向量请求与预取地址的寄存控制

## 结构

共享权重配置在输入槽位清空后的周期预留下一项窗口请求。已经接收的请求继续按标签返回，计算发射在对应边沿保存操作数并释放槽位。私有权重配置支持同周期释放与预留。

`tap_last_modulo` 和 `weight_prefetch_q` 与核位置共同更新。配置载入、位置归零和递增分别准备下一周期需要的末项资格与预取地址，全部七处相关更新都保存同一组关系。`tap+1` 与 `tap+2` 通过独立的普通 RTL 加法器并行计算，读取端口直接使用保存的地址。末项比较继续使用 `add_equal`，保留定宽回绕和四态进位一致性；扩展宽度的 `tap_last_wide` 比较保持完整计算范围。

`state_pool_store`、`state_dw_execute` 和 `state_weight_read_phase` 与状态字同时保存，分别服务于极值池化、深度卷积发射和共享权重读取。全部 89 处状态更新共同维护这些标志。有效通道掩码与通道数在四处更新中共同保存，供权重、量化和结果写入选择使用。

## 功能验证

| 配置或检查 | 结果 |
| --- | --- |
| 生产配置：16 通道、8 PE、64 位总线、8 路窗口、7 个共享 RAM 银行、独立量化 | 616 项任务，170,743 个数值输出通过 |
| 通用配置：16 通道、16 PE、32 位总线、4 路窗口、私有存储、共享量化 | 616 项任务，170,743 个数值输出通过 |
| 生产配置固定等待 | 40 项任务，103,743 个输出通过 |
| 完整源码末项状态和预取地址证明 | 6 组参数均完成一步归纳证明 |
| 共享与私有窗口请求资格 | 2 组全部二值输入证明通过 |
| 末项状态与预取地址四态比较 | 9 种位宽，216,009 组比较通过 |
| 保存的池化状态资格 | 89 处更新，4 项 SAT 检查及 4,096 个四态控制字通过 |
| 排空条件四态比较 | 131,072 次比较通过 |

源码证明保留实际 `tap`、`taps`、`tap_last_modulo` 和 `weight_prefetch_q` 的全部时序逻辑，其余寄存器与存储输出作为自由输入。仅第一个采样周期施加复位，后续复位、运算模式和控制输入均保持自由。参数覆盖生产、通用、小型实例和最大支持的卷积及池化核范围。

四态测试使用从实际 RTL 提取的算术实例，分别检查末项状态、保存的预取地址和最终读取地址。核位置的全部写入来自复位常量、位置归零或当前值的递增，测试同时检查复位后的核位置已知性；配置、控制及后续复位可以包含未知值和高阻态。

生产回归检查返回权重的地址和 128 位内容、保存的权重内容、输入暂停、无效坐标跳过、跨 tap 运行、任务切换、错误恢复、写入末拍以及写回负载稳定。该配置覆盖 282,743 个等待输入的周期、7,546 次无效 tap 跳过和 148 个错误处理周期。

当前源码与参考源码的 616 项生产任务逐项周期及全部统计相同，总计 3,423,269 周期。固定等待的 40 项任务同样逐项一致，总计 1,071,159 周期。测试按执行顺序比较名称重复的案例，保留同周期请求与响应、读写交叠及背压统计。

## 生产参数综合与连接检查

两次独立综合使用相同公共模块、器件目标和生产参数。

| 项目 | 参考源码 a03aa94a | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 10,498 | 10,399 |
| LUT RAM 的名义 LUT 数 | 176 | 176 |
| 名义 LUT 合计 | 10,674 | 10,575 |
| 触发器 | 6,417 | 6,437 |
| DSP | 73 | 81 |
| RAMB18 | 9 | 9 |
| 完整寄存器连接图最大组合级数 | 10 | 10 |
| 寄存器到权重读取地址 | 2 | 2 |

`i_weight_read_valid` 到 `win_req_valid` 无组合连接，池化控制到累加数据的局部最长路径为六级，寄存器到权重读取使能为一级。`report_ports.py` 在分析数据中标记接口边界，统计实际寄存器与接口之间的连接。

窗口、区间及组选择的设计和专用检查见 [窗口控制说明](../vector_window_control/README.md)。保存的读取阶段、通道掩码及权重归并见 [权重资格说明](../vector_weight_qualification/README.md)。

以上资源与级数来自独立 `vector_engine` 实例。完整 SoC 测量包含共享存储及 DMA 等外围连接，器件实现报告用于确认 150 MHz 时序。

## 复现

从仓库根目录执行源码证明与状态控制检查：

```sh
python test/vector_request_boundary/run_formal.py --out /tmp/vector_request_formal
python test/vector_control_flags/run.py --out /tmp/vector_request_control
```

生产数值回归使用以下参数，编译与运行期间保持源码不变：

```sh
python test/vector_engine/run.py --out /tmp/vector_request_production --pes 8 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 --bus-width 64 --window-lanes 8 --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 --shared-ia-banks 2 --check-weight-write-stage --rtl-assertions --stable-stimulus --xilinx
```

同一命令附加 `--skip-build --perf` 运行固定等待测试。通用配置使用 `--pes 16 --cache-sets 4 --bus-width 32 --window-lanes 4 --shared-quant`，保留 `--rtl-assertions --stable-stimulus`，其余存储选择与 FPGA 选项采用默认值。

`compare_cycles.py` 按执行顺序比较两个 JSON 结果。固定等待结果使用 `--fixed-wait`。详细参数、源码校验值、形式证明记录及逐项周期结果保存在 `validation.json`。
