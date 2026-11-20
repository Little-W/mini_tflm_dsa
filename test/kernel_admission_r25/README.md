# 核加载任务接收请求

参考提交为 `c4edde85f284bdd71d4c254e2456ffae955d4016`。生产修改涉及 `kernel_loader.sv` 和 `npu_top.sv`。

## 当前组合关系

核加载器的后台空闲条件为：

```systemverilog
Q = prefetch_state != PF_PENDING && !transfer_active &&
    !prefetch_check_pending && !ext_dma_busy && response_slots_active == 0;
```

新的 `o_admission_request` 输出使用以下组合关系：

```systemverilog
Rq = !prefetch_state[1] && !cache_flush && ctrl_load_req &&
     (!command_mode_q || (buf_load_ready && !init_cfg));
```

对全部状态编码和输入组合，`Q && load_weight_req` 与 `Q && Rq` 相同。`Q` 为真时，待发预取和在途传输均被排除；处于已加载或已缓存状态时，需求请求为零；空状态下仅需检查控制请求、命令模式、缓冲接收资格、配置和清除条件。

FPGA 实现将这六个输入接入一个 LUT6，`INIT=64'h0010_0010_1010_0010`。输入顺序为预取状态高位、`cache_flush`、`ctrl_load_req`、`command_mode_q`、`buf_load_ready`、`init_cfg`。通用实现使用相同布尔表达式。

顶层用 `Rq && block_dma_arbiter_o_kernel_eligible` 生成 `admission_kernel_occupied`，原有末级就绪 LUT 继续同时检查 `Q` 和中止条件。原 DMA 请求、授予、`prefetch_idle`、配置开始关系及全部寄存过程保持一致，新增状态位和新增接口周期均为零。`o_admission_request` 只供顶层任务接收使用。

## 形式与数值验证

实际组合证明从生产源码提取完整请求与后台空闲表达式、全部仲裁授予、AXIL 开始条件以及顶层就绪、配置开始和向量开始表达式。12 组证明全部通过，覆盖通用与 FPGA 实现、量化开关、时钟门控开关及 `REG_WIDTH=8/32/64`。全部状态位、所有请求方编码、中止及其他输入均无附加假设；同时比较原请求、空闲、启动和所有接收输出。LUT 的 64 项真值全部通过。

完整核加载器在以下配置比较全部原公开输出和全部原状态，共通过 49,064 个等价位。证明保留复位、配置清除、响应完成、授予撤销及同时事件的原优先级。

| SIZE | COUNT_WIDTH | BUS_WIDTH | 实现 | 等价位 | 独立状态位 |
|---:|---:|---:|---|---:|---:|
| 4 | 8 | 32 | 通用 | 2,759 | 2,519 |
| 16 | 32 | 64 | 通用 | 15,469 | 15,229 |
| 16 | 29 | 32 | FPGA | 15,418 | 15,178 |
| 16 | 29 | 64 | FPGA | 15,418 | 15,178 |

实际 FPGA 数值回归采用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`。共运行 29,443 周期，检查 72,960 个权重值，完成 312 次 DMA 启动与完成、285 个发送块、73 次缓存命中、25 次缓存丢弃及 4 个清除场景；全部统计与同源参考核加载结果一致。测试同时覆盖 INT8/INT16、im2col、尾块、两个并发 DMA 上下文和输出背压，C++ 仿真启用未定义行为检查。

独立审阅再次核对实际 LUT 输入及真值、原寄存过程、原核加载公开输出和顶层新信号用途；结果保存在 `measurement.json`。

## 局部真实连接测量

测量使用实际核请求、后台空闲、仲裁授予、AXIL 时钟门控开始及顶层接收表达式。控制器、缓冲器及其他模块的条件在列明的寄存输入处形成边界。采用 `physical-cost`、最大六输入 LUT、500 ps 连线成本及 6,667 ps 目标，ABC9 等价和完整组合图检查均通过。

| 指标 | 参考 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 37 | 38 |
| 测量寄存器 | 116 | 116 |
| 范围内最长寄存器路径 | 7 | 7 |
| `prefetch_state[1]` → 接收请求组合输出 | 3 | 1 |
| `prefetch_state[1]` → `admission_kernel_occupied` | 4 | 2 |
| `prefetch_state[1]` → `quiescent` | 4 | 4 |
| `prefetch_state[1]` → `sa_ready` | 5 | 5 |
| `prefetch_state[1]` → 向量开始 | 7 | 7 |
| `prefetch_state[0]` → `sa_ready` | 5 | 3 |

请求及占用条件的分段统计直接读取已映射连接，终点为内部组合信号。当前范围最长的预取状态路径经过 `prefetch_check_pending`、`quiescent` 和就绪判断；原请求选择的串行依赖已从接收占用条件中移除。完整 SoC 的寄存器路径和物理 LUT 位置由整机报告独立统计。

## 源码与结果

| 文件 | 当前 SHA-256 | 参考 SHA-256 |
|---|---|---|
| `rtl/npu/loaders/kernel_loader.sv` | `f569287877e9eef136da7da74c49bec8330763c7f33e6d1593803ac7fc7fb309` | `affdd6a1a6c188b46f191a534d77dc2050184be44583a560ebbe28b856f13212` |
| `rtl/npu/top/npu_top.sv` | `7e7f9d87ace35234d34d1cf0793d5aea9b04d95fdd2be84350c2078d3f8a2873` | `732909545c9a217a93320a4dd7ae1fba45375cdbbd6feedad637343721f0703a` |

`measurement.json` 保存当前与参考源码 SHA、完整形式结果、数值统计、局部路径和原始记录摘要。所有证明与运行均重新核对实际源码。

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/kernel_admission_r25/run_formal.py --out build/kernel_admission_r25/formal
python3 test/kernel_prefetch/run.py --out build/kernel_admission_r25/numeric \
  --verilator verilator-modern --bus-width 64 --count-width 29 --fpga
python3 test/kernel_admission_r25/measure.py --formal build/kernel_admission_r25/formal \
  --out build/kernel_admission_r25/local \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/kernel_admission_r25/segments.py --local build/kernel_admission_r25/local
python3 test/kernel_admission_r25/collect.py --build build/kernel_admission_r25
```
