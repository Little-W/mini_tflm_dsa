# 部分和帧请求的保存资格

`ps_frame_store` 在已有 `request_capture` 接收边沿同时保存两项条件：请求合法且容量足够，以及请求初始化数据或访问其他帧编号。请求等待期间，当前帧编号保持稳定；接收、取消或清除请求时，同步更新请求资格。

`ps_frame_prepare_branch` 在六输入组合表达式内检查首行读写冲突，并分别形成空闲接收、完成交接和首行读取资格。`ps_frame_prepare_enable` 并行合并帧控制完成条件和返回队列空闲条件，直接形成新帧准备使能。模块接口、帧接收周期、存储容量及同步读写时序保持相同。

## 完整生产模块测量

参数为 `MAX_FRAME_ROWS=256`、`FRAME_COUNT=16`、`POOL_BYTES=49152`、`BANK_BYTES=8192`、`EXTERNAL_RAM=1`、`p_fixed_ps_channels=1`。参考与当前实现采用相同依赖和 `physical-cost` 设置：最大 LUT 输入数 8、布线延迟 300 ps、目标周期 6667 ps。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1488 | 1484 |
| FF | 1034 | 1036 |
| DSP | 18 | 18 |
| RAMB18 | 15 | 15 |
| 完整模块最长寄存器路径 | 11 | 9 |
| 保存的请求帧编号到 `frame_ready` | 6 | 无组合连接 |
| 保存的请求帧编号到 RAM 读使能 | 7 | 无组合连接 |
| 新增保存资格到 `frame_ready` | — | 2 |
| 全部状态到 `frame_ready` | 6 | 4 |
| 全部状态到 RAM 读使能 | 8 | 6 |
| 全部状态到容量故障寄存器 | 10 | 9 |

## 完整验证

形式检查覆盖生产 256 行、紧凑布局 512 行、内部存储 47 行和循环存储 16 行四组参数，并分别采用显式通用与 FPGA 编译方式。

每组先直接对完整实际模块进行时序归纳，证明保存的请求资格等于原有配置、请求合法性和容量条件的组合；请求有效期间，保存的帧关系等于实际帧编号和初始化标记的组合。首次采样复位后，全部外部输入和复位自由变化。

随后使用已经证明的两项内部状态关系，比较参考与当前完整模块的全部公开输出、共同状态及内部存储内容。8 项完整模块等价证明共覆盖 129388 个状态和信号位，外部功能输入没有附加限制。

另外执行了以下测试：

- 4 组参数与两种编译方式共 65536 个周期的完整模块四态比较，每拍检查全部公开输出，覆盖未知值、高阻态、配置切换、请求接收和取消。
- 通用与 FPGA 两种生产参数数值回归，共 1356 条帧命令、471392 个 INT32 数值、59860 个周期和 14456 个并行读写周期；每个周期比较全部公开输出。

```bash
python test/ps_request_ready/run_formal.py --mode generic --out build/ps_request_ready_generic
python test/ps_request_ready/run_formal.py --mode fpga --out build/ps_request_ready_fpga
python test/ps_request_ready/run_four_state.py --out build/ps_request_ready_four_state
python test/ps_request_ready/run_numeric.py --profiles 8192:7 --max-frame-rows 256 --out build/ps_request_ready_numeric
python test/ps_request_ready/run_numeric.py --profiles 8192:7 --max-frame-rows 256 --fpga --out build/ps_request_ready_numeric_fpga
```

`validation.json` 保存参数、源码和日志摘要，`measurement.json` 保存完整资源统计与实际连接路径。
