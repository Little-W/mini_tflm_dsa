# 写回请求准备与普通算术推断

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

## 请求接收和数据发送

`vector_banked_writeback` 在请求有效后先保存地址连续性与缓冲容量检查结果。三个单比特寄存器分别表示请求已经准备、地址可以连接以及容量足够。复制循环每周期写入一个总线字，最后一个总线字存入后通过 `request_ready` 确认接收。生产方在确认前保持地址、长度、标志和结果数组稳定。

准备阶段使地址比较与 `publish_fire`、复制使能和公开 `ready` 分属不同周期。请求提交或缓冲发布后清除准备标志，随后依据新的缓冲边界计算下一项请求。取消请求或 `flush` 会停止未完成的复制；已经确认接收的数据按正常事务顺序发送。

发送侧使用两个字节银行组，保存待发送结果和当前 AXI 写事务。每个事务内部每周期提供一个有效数据拍；背压期间数据、字节使能、地址和突发长度保持稳定。每个响应对应一次已经发送全部数据的事务，响应错误与完成信号同周期输出。

## 普通 RTL 算术

配置范围、坐标步长、通道数量、填充值和 AVG 余数使用保留完整位宽的普通加减表达式。实际运算结果带有 `use_dsp` 属性，由综合工具推断算术资源。数据位宽、符号扩展、溢出位和原有寄存周期保持一致。

`test/vector_medium_arithmetic/run.py` 从真实源代码提取 22 个运算表达式，把配置字段转换为相同宽度的独立输入，比较全部输入范围和四态结果。配置检查模块另有完整状态等价证明。所选算术映射通过官方算术与 DSP 模型逐种参数检查。

## 功能与协议结果

| 验证项目 | 配置与结果 |
|---|---|
| 生产向量 | 8 PE、TILE16、BUS64、8 个窗口通道、共享存储、独立量化；616 项任务、170,743 个数值输出通过 |
| 通用向量 | 16 PE、TILE16、BUS32、4 个窗口通道、独立输入存储、共享量化；616 项任务、170,743 个数值输出通过 |
| 写回参数 | 9 种参数组合，TILE1/2/3/16/64，BUS32/64/128，两种合并策略 |
| 写回数据与响应 | 11,940 个请求、721,668 个字节、656 个错误响应通过逐字节与事务检查 |
| 取消与背压 | 9 次准备阶段取消、7 次已经写入数据后的部分复制取消；授权等待、数据暂停和连续发送均通过 |
| 原生算术 | 4 组 TILE 与池化容量参数通过形式检查，131,072 组四态样本、2,883,584 个运算结果逐位一致 |
| 配置状态 | TILE4/16/64 的状态与公开结果等价检查，以及完整 64 位激活范围检查通过 |
| 算术映射 | 57 个选中算术单元的 23 种实际参数组合通过完整输出形式检查 |

完整向量测试包含 Add、Softmax、深度卷积、极值与平均池化、向量归约、INT16 输入、非对齐字节输出、尾通道、读写错误和连续恢复。权重预取地址与内容、输入银行写入、完成事件与状态关系均启用断言。

## 周期和资源

固定等待条件下，40 项性能及错误恢复任务使用相同前端和存储输入序列。总周期从 1,069,062 变为 1,071,159，增加 2,097，约 0.196%。增加的准备周期可以与 DW 计算及已有写事务重叠；每个 AXI 事务内部保持连续数据发送。

| 代表任务 | 参考周期 | 当前周期 | 增加周期 |
|---|---:|---:|---:|
| `pipeline_dw_c16` | 4,129 | 4,130 | 1 |
| `pipeline_dw_tail_c3` | 1,447 | 1,448 | 1 |
| `perf_avg_c32` | 36,496 | 36,624 | 128 |
| `perf_max_c32` | 1,735 | 1,767 | 32 |
| `perf_hadamard_s16` | 3,118 | 3,182 | 64 |
| `perf_add_resnet_16384` | 328,832 | 329,856 | 1,024 |

`pipeline_dw_tail_c3` 覆盖 22 次同周期窗口请求与响应。`pipeline_dw_c16` 的同周期请求与响应计数为零，仍检查至少两项并发请求、连续量化、计算与量化重叠、计算与写出重叠以及输出字节与事务数量。

| 独立向量综合指标 | 参考 R29 | 当前设计 |
|---|---:|---:|
| 逻辑 LUT | 11,320 | 11,128 |
| 分布式存储 LUT | 176 | 176 |
| 名义 LUT 合计 | 11,496 | 11,304 |
| FF | 6,306 | 6,309 |
| DSP | 52 | 71 |
| RAMB18 | 9 | 9 |
| 最长寄存器间组合单元数 | 10 | 10 |

测量使用生产参数和完整寄存器连接图，图中所有节点均已遍历。150 MHz 还需目标器件的布局、布线时序报告确认。资源表为独立向量实例，完整 SoC 的资源与路径由统一源码版本单独测量。

## 复现

```bash
python test/vector_banked_writeback/run.py --out build/writeback_protocol --verilator verilator --jobs 1
python test/vector_medium_arithmetic/run.py --out build/vector_native_arithmetic --iverilog iverilog --vvp vvp
python test/vector_config_ranges/run.py --out build/vector_config_formal --reference 0097b66ed57e1b8ef00e402e89dc5b274f1626be
python test/vector_engine/run.py --out build/vector_prepare_production --verilator verilator --pes 8 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 --bus-width 64 --window-lanes 8 --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 --shared-ia-banks 2 --check-weight-prefetch --rtl-assertions --stable-stimulus --xilinx
python test/vector_engine/run.py --out build/vector_prepare_generic --verilator verilator --pes 16 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 --bus-width 32 --window-lanes 4 --shared-quant --rtl-assertions --stable-stimulus
python scripts/fpga/open_fpga_synth.py --case-config test/vector_engine/production_synthesis_cases.json --cases vector --out build/vector_prepare_synth --max-register-path-cells 10 --lock-file ../soc_synth.lock
```

在生产向量命令末尾添加 `--skip-build --perf` 可重复固定等待的周期测试。精确文件摘要、全部任务周期和资源记录保存在 `request_prepare_validation.json`。
