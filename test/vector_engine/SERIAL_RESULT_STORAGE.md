# 向量结果存储与 AVG 流水

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

## 当前结构

极值池化通过 `PE_COUNT` 个八位限幅器处理当前通道组，读取端口与计算通道共用。`POOL_STORE` 按通道组写入完整输出，最后一组完成后准备写回请求。生产配置为 `TILE=16`、`PE_COUNT=8`，最多分两组提交。

深度卷积在最后一组 PE 结果写入 `acc_buf` 后生成整行快照。共享部分和存储和本地快照都读取完整的累加数组。快照处理期间，下一像素的初始化与后续量化、写回按现有预留状态协调。

AVG 的非二次幂除数运算分别保存八位幅值、完整九位有符号结果及激活限幅后的字节。符号恢复和范围比较分处两个寄存阶段，每个输出元素增加一个准备周期。二次幂除数继续使用舍入移位通路。

Add、AVG 和 Softmax 的串行输出共同保存字节数据、下标和有效位，下一时钟边沿写入 `acc_buf` 的低字节。写回请求的元数据准备周期覆盖最后一个字节的提交；内部断言检查写回接受请求时不存在尚待提交的串行字节。极值池化保留按组并行写入。各数组和算术均采用普通 SystemVerilog 描述。

## 独立综合

采用 `production_synthesis_cases.json` 的生产参数：8 个 PE、64 位总线、8 路窗口，独立量化与共享权重、部分和存储。

| 项目 | 结果 |
|---|---:|
| 逻辑 LUT | 11,315 |
| 分布式存储名义 LUT | 176 |
| 名义 LUT 总数 | 11,491 |
| 触发器 | 6,306 |
| DSP48E1 | 52 |
| RAMB18E1 | 9 |
| 寄存器间最长组合单元数 | 10 |
| 已遍历连接图节点 | 31,521 / 31,521 |

第七轮保存的同参数独立测量为 12,308 个名义 LUT，本结构减少 817 个。完整 SoC 的资源数量和器件时序由整机综合及布局布线测量确定。

## 数值和协议检查

| 配置 | 参数 | 通过任务 | 比较输出 |
|---|---|---:|---:|
| 生产 | 8 PE，64 位总线，8 路窗口，独立量化，7 个共享银行，每个 8,192 字节，2 个输入银行 | 616 | 170,743 |
| 通用 | 16 PE，32 位总线，4 路窗口，共享量化，本地权重和快照 | 616 | 170,743 |

两种配置均包含 DW、平均值与极值池化、INT8/INT16 向量运算、143 项 Add 和 273 项 Softmax 测试，并启用 RTL 内部断言。输入值、配置尺寸和总线等待使用独立随机序列，便于逐项比较。

检查保留以下硬件行为：

- 独立整数参考计算的全部输出，以及输出区域之外的存储内容。
- `AR`、`AW`、`W` 在背压期间保持负载稳定；读取地址属于已分配区域，突发传输不跨越 4 KiB 边界。
- 窗口请求在任务完成前全部结束，量化输入数量准确，连续通道组能够连续提交。
- `pipeline_dw_c16` 至少存在两个在途窗口，并检查乘加、量化和写回重叠、1,024 个输出字节及 16 次合并写事务。
- 固定等待条件下，`pipeline_dw_k1_c16` 检查 512 个输出字节及 8 次合并写事务。
- `pipeline_dw_tail_c3` 明确检查窗口请求与响应在同一时钟边沿接收，生产配置观测到 22 次。
- 共享权重预取检查地址、数据、暂停保持、填充坐标、跨卷积核位置和任务切换。
- 读写错误、参数范围错误和后续任务恢复；性能测试完成后同样执行异常与恢复任务。
- 写回接受串行结果前全部字节已提交，AVG 保存的九位有符号数与对应幅值、符号一致。

## 固定等待周期比较

参照版本为提交 `0097b66ed57e1b8ef00e402e89dc5b274f1626be`。两侧使用相同的前端、总线服务、数据序列和测试源码，RTL 差异仅在 `vector_engine.sv`。40 个任务均通过数值和协议检查，其中 24 个性能任务的周期如下。

| 任务组或任务 | 参照周期 | 当前周期 | 增加周期 |
|---|---:|---:|---:|
| 24 个性能任务合计 | 1,064,368 | 1,066,446 | 2,078，约 0.1952% |
| `perf_avg_c32` | 34,576 | 36,496 | 1,920 |
| `perf_global_avg_25x5_c64` | 8,947 | 9,011 | 64 |
| `perf_max_c32` | 1,703 | 1,735 | 32 |
| `perf_mnist_max_14_c16` | 2,254 | 2,303 | 49 |
| `perf_dw_c64_s2` | 34,545 | 34,549 | 4 |
| `pipeline_dw_k1_c16` | 795 | 796 | 1 |
| `pipeline_dw_c128_s2` | 12,582 | 12,590 | 8 |
| `pipeline_dw_c16` | 4,129 | 4,129 | 0 |
| `pipeline_dw_tail_c3` | 1,447 | 1,447 | 0 |

其余性能任务周期相同。`pipeline_dw_c16` 的同周期窗口请求与响应次数在两侧均为零，新增尾通道任务在两侧均为 22 次。两个任务共同检查完整通道组的计算并发和尾通道窗口的同周期握手。

包含 16 个异常与恢复任务后，40 项总周期为 1,066,978 和 1,069,062。完整逐项周期、源码 SHA256、构建记录及测量记录 SHA256 保存在 `serial_result_validation.json`。

## 复现

以下命令在仓库根目录执行，所需工具应位于 `PATH`。大型综合使用统一锁文件。

```bash
python scripts/fpga/open_fpga_synth.py --out /tmp/vector_serial_measurement --case-config test/vector_engine/production_synthesis_cases.json --cases vector --max-register-path-cells 10 --require-register-path-limit --lock-file ../soc_synth.lock
python test/vector_engine/run.py --out /tmp/vector_serial_production --pes 8 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 --bus-width 64 --window-lanes 8 --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 --shared-ia-banks 2 --check-weight-prefetch --rtl-assertions --stable-stimulus --xilinx
python test/vector_engine/run.py --out /tmp/vector_serial_production --pes 8 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 --bus-width 64 --window-lanes 8 --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 --shared-ia-banks 2 --check-weight-prefetch --rtl-assertions --stable-stimulus --xilinx --skip-build --perf
python test/vector_engine/run.py --out /tmp/vector_serial_generic --pes 16 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 --bus-width 32 --window-lanes 4 --shared-quant --rtl-assertions --stable-stimulus
```
