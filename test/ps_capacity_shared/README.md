# 部分和共享容量计算

`ps_frame_store` 在接收配置的边沿保存存储池总行数，与目录行间隔使用同一个更新条件。请求接收时，帧编号与目录行间隔的乘积同时提供帧起始地址和剩余容量计算。实际行数及预留行数分别使用分组比较，检查同一个剩余容量。

请求接收、帧准备、读取、写入及回放的时钟周期保持一致。容量、存储端口、并行访问能力和所有公开输出保持一致。配置和帧编号包含未知位时，逐帧容量表提供四态选择结果。

## 综合测量

比较提交 `8cbe40d9` 与当前源码，使用相同依赖和完整 `ps_frame_store`。生产参数为 16 个帧槽、每帧最多 256 行、49152 字节存储池、8192 字节物理块及四个固定外部通道。映射采用 `physical-cost`、最大八输入查找结构、300 ps 连线估计及 6667 ps 目标周期。

| 项目 | 比较版本 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1484 | 964 |
| LUTRAM / SRL | 0 / 0 | 0 / 0 |
| 触发器 | 1036 | 836 |
| DSP48E1 | 18 | 3 |
| RAMB18E1 / RAMB36E1 | 15 / 0 | 15 / 0 |
| 完整模块内部最长组合路径 | 9 | 10 |
| 保存的请求资格到 `frame_ready` | 2 | 2 |
| 保存的请求资格到 `ram_read_en` | 4 | 4 |
| 全部内部状态到 `frame_ready` | 4 | 4 |
| 全部内部状态到 `ram_read_en` | 6 | 6 |

保存的请求帧编号与 `frame_ready`、`ram_read_en` 之间均没有组合连接。测量中的 DSP 和存储资源由普通 RTL 表达式推断。组合级数来自实际连接图，器件实现时序由布局布线结果确定。

## 功能检查

形式验证包含生产 256 行、紧凑 512 行、内部存储 47 行、轮转外部通道及三个帧槽五种参数配置，分别使用通用和 FPGA 编译方式。

每种配置先在完整实际模块中归纳证明：各帧容量等于配置总行数减去该帧的定宽起始行。首次采样复位，此后复位、配置和全部功能输入均自由变化。随后使用已经证明的内部状态关系，检查完整模块的所有公开输出、共同状态和存储内容，不增加外部输入条件。

五种参数配置在两种编译方式下共运行 81920 个四态周期。输入包含未知及高阻状态的请求、帧编号、行数、配置数据和控制信号；全部公开输出每周期比较，包括未读取时的地址。真实存储数值测试在两种编译方式下共完成 1356 条帧命令、471392 个 INT32 数值检查及 59860 个时钟周期，包含配置切换、容量压力和读写重叠。

## 重新运行

```sh
python3 test/ps_capacity_shared/run_formal.py --mode generic --out build/ps_capacity_shared/formal_generic
python3 test/ps_capacity_shared/run_formal.py --mode fpga --out build/ps_capacity_shared/formal_fpga
python3 test/ps_capacity_shared/run_four_state.py --out build/ps_capacity_shared/four_state
python3 test/ps_request_ready/run_numeric.py --reference 8cbe40d9 --profiles 8192:7 --max-frame-rows 256 --out build/ps_capacity_shared/numeric_generic
python3 test/ps_request_ready/run_numeric.py --reference 8cbe40d9 --profiles 8192:7 --max-frame-rows 256 --fpga --out build/ps_capacity_shared/numeric_fpga
python3 test/ps_capacity_shared/run_measurement.py --out build/ps_capacity_shared/measurement
```

`validation.json` 保存各项检查结果和源码、脚本、日志摘要。`measurement.json` 保存完整父模块的成对资源统计、指定路径级数及网表摘要。
