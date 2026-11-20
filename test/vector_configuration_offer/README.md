# 向量配置描述符保持

`vector_engine` 在 `CONFIGURE` 状态持续置位 `dma_cfg_valid`。配置接受仍由
`dma_cfg_valid && dma_cfg_ready` 决定，状态机仍在 `dma_cfg_ready` 有效的边沿进入
`TILE_INIT` 或 `VECTOR_INIT`。该表达式移除了 `ready` 到 `valid` 的组合依赖。

测试所需的选择输入和观察逻辑生成在 `build` 目录。结果见 [measurement.json](measurement.json)。

## 配置等待性质

`run_formal.py` 读取实际 `vector_engine`、配置检查器和写回单元，保留向量状态、
检查器状态、写回状态、配置字段和范围字节数。其余数据寄存器扩展为每周期任意值，
用 Yosys SAT 从复位后的状态完成一步归纳证明，外部输入没有额外取值限制。

证明覆盖以下性质：

- `CONFIGURE` 期间 `rd_req`、`rd_start`、`win_req_valid`、`wr_req`、`wr_start`
  和 `src_wvalid` 均为零。
- 配置等待期间，卷积描述符、卷积使能、范围使能以及四组范围起点和终点保持稳定。
- 新旧表达式的配置接受事件相同。
- 配置前置状态与任务完成状态保持写回单元空闲，`CONFIGURE` 期间配置检查器处于空闲状态。

该证明使用生产参数 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64`，保留 53 个相关寄存器单元，
将其余 92 个数据寄存器单元作为任意输入。被扩展的数据条件可以产生更多控制路径，
原有状态转移和配置寄存条件保持完整。

## 仲裁和 DMA 使用条件

配置有效信号还参与仲裁和 DMA 的请求处理。脚本从实际源码提取这些表达式，
在 `CONFIGURE` 没有客户端请求的条件下，证明以下结果对其他输入和状态的全部取值相同。

| 实际使用者 | 比较内容 |
|---|---|
| `axi_block_dma_arbiter.rd_next_client` | 下一请求方选择 |
| `rd_grant_client` 更新 | 当前授权保持、窗口授权取消与下一授权 |
| `dma_conv_cfg_valid` 和 `conv_cfg_ready` | 实际配置接受事件 |
| `win_accept_allowed` | 窗口请求接受事件 |
| `axi_dual_block_dma.rd_start_ready` | 已暂存读取命令的接受事件 |
| `image_start_ready` | 图像读取接受事件 |
| 窗口队列 `req_valid` | 入队事件 |

已经保存的普通读取命令使仲裁器暂缓发送配置；提前有效的配置不会改变该命令的推进。
窗口请求为零时，窗口授权在两种表达式下均按原条件释放。内部就绪值可能在没有有效请求时变化，
对应的接受事件和下一周期状态相同。

## 完整 NPU 公开行为

`run_system.py` 构建实际完整 NPU，并加载 Yosys 安装目录中的官方
`LUT1` 至 `LUT6`、`LUT6_2`、`MUXF7`、`MUXF8`、`DSP48E1`、`FDRE` 和 `CARRY4` 模型。
运行参数为 16×16 计算阵列、8 个向量 PE、64 位 AXI、7 个 8 KiB 共享银行、
16 个部分和帧及 4 KiB im2col 数据缓存。

一次编译提供两种配置有效表达式的选择位。每次运行在复位前固定该位，按同一随机种子和
相同输入序列分别执行任务。测试逐周期记录系统就绪、完成、错误码、全部 AXI 握手信号和
有效请求的地址、长度、类型、写数据、字节使能与结束标志，再逐字节比较两份记录。
任务周期、完成错误码和结果数值也分别检查。

每次运行包含 15 个交替任务：按张量量化矩阵、按通道量化矩阵、帧调度矩阵、
INT8/INT16 向量求和、最大池化、depthwise、非法向量配置，以及读取错误后的恢复任务。
IA、kernel、bias、quant 四类普通客户端均实际产生过读取请求。在整个 `run_vector` 期间，
测试断言这些普通请求均为零；在 `CONFIGURE` 期间另检查向量自身的读取与窗口请求、
矩阵控制器启动和普通 DMA 配置初始化。

| 接收端初始等待 | 每种表达式的任务数 | 数值检查 | 执行周期 | 配置等待周期 | 逐周期记录大小 |
|---:|---:|---:|---:|---:|---:|
| 0 | 15 | 1,974 | 10,238 | 0 | 698,736 字节 |
| 400 周期 | 15 | 1,974 | 11,039 | 750 | 748,672 字节 |

两组记录均逐字节相同。等待场景在配置接收端扩展背压，配置接受继续使用实际 `cfg_fire`。
读取错误触发实际 NPU 中止与复位恢复，因此该场景累计覆盖 750 个配置等待周期。

完整 NPU 的普通客户端互斥由上述实际任务断言验证；无输入约束的归纳证明覆盖向量单元自身的
状态和配置载荷。仲裁与 DMA 的组合证明明确保留客户端请求为零这一条件，全部范围记录在报告中。

## 源码对应

参考源码提交为 `a9dac7c6c3531d0390f529affb97d260930e11bd`，参考向量文件 SHA256 为
`7f407f1b36a5d4570d69b1565c51090cc4b3a4013d4fd7a6fb2b69ba690dca0e`。
当前向量文件 SHA256 为
`e1df55e8021c7473584a81c3a9f23257f94b6da8a81653d3271257efd6876482`。
`collect_report.py` 按源码词法内容核对配置有效表达式与测试模型一致，并逐项复核所有参与测试的文件哈希。

## 重现

运行环境需要 Python 3、支持 Slang 的 Yosys/Pyosys、现代 Verilator 和 C++ 编译器。
脚本同时接受更改前后的配置有效表达式。

```sh
python3 test/vector_configuration_offer/run_formal.py \
  --out build/vector_configuration_offer/formal
python3 test/vector_configuration_offer/run_system.py \
  --out build/vector_configuration_offer/system --verilator verilator-modern --jobs 2
python3 test/vector_configuration_offer/collect_report.py \
  --build build/vector_configuration_offer \
  --candidate /path/to/candidate/rtl/npu/conv/vector_engine.sv
```

已有模拟器可用 `--skip-build` 重复运行。该选项核对全部编译输入、生成模型、参数和官方原语模型后使用已有二进制。
