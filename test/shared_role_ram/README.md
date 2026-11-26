# 共享 IA 与部分和存储的独立端口

`ia_ps_channel_ram` 为每个可分配存储块提供 IA 访问与四个部分和通道。`ia_ps_role_ram` 使用普通同步数组描述两个独立地址端口：端口 A 写入 IA 或读取部分和，端口 B 读取 IA 或写入部分和。每个端口的写数据来源固定，可减少共享写端口前的 128 位数据选择。

## 接口行为

`p_allow_inactive_return_updates` 默认为 `0`，保持原有返回行为。设为 `1` 时，FPGA 分支允许写入更新未拥有该共享块的通路返回值。同一配置中，拥有该块的通路在首次有效读取后，返回值持续保持至下一次有效读取。配置切换后，消费者通过本次配置的首次读取建立数据可用状态。

`npu_top` 的固定部分和通道实例开启这一选项。IA 与部分和仍按配置分配互斥的物理空间；各通道的独立读写地址、逐字节 IA 写掩码、存储容量、读取周期和同拍独立读写能力保持一致。ASIC 分支使用原有存储行为。

向量量化在读有效信号结束之后仍可使用部分和返回值，因此检查覆盖首次读取之后的全部保持周期。矩阵 IA、部分和解码、向量权重与向量量化消费者均检查本次配置的读取历史。

共享段先形成地址、布局和读写冲突资格，再由 `ia_ps_role_ram.i_access_enable` 在实际存储端口处统一控制本周期访问。该输入默认为 `1`；关闭时保持存储内容和两个同步返回寄存器。全局任务接收或中止条件只经过末级使能逻辑。

## 验证结果

| 检查 | 结果 |
|---|---:|
| 完整通道命令、状态与连续返回历史的时序归纳 | 6 组通过 |
| 默认选项的完整命令及状态归纳 | 16 组通过 |
| 默认选项的四态比较 | 131,072 次通过 |
| 真实 RAM 数组的一步状态与读取证明 | 32 项通过 |
| 真实 RAM 数组逐拍比较 | 5 组，各 8,192 周期通过 |
| 完整生产 AXI 固定及随机延迟任务 | 208 项通过 |
| 固定及随机延迟任务的数值输出比较 | 104,428 个通过 |
| 读有效结束后继续使用部分和的量化周期 | 13,054 个通过 |
| 非紧凑输入配置的完整 NPU 任务 | 96 项，235,528 个数值结果通过 |
| 紧凑输入配置的完整 NPU 任务 | 94 项，253,448 个数值结果通过 |

完整通道证明在首次采样施加复位，之后的配置、使能、地址、写数据、掩码与复位均保持自由。证明同时检查实际读写命令、物理段的读取历史及公开输出选择；已读取的输出在暂停和未读周期中继续比较。真实数组测试在每拍后检查每个共享存储字，覆盖配置切换、独立并行访问、部分写入、非法请求与 `X/Z` 控制。

生产 AXI 测试通过 `consumer_observer.sv` 检查 IA 行、部分和解码、向量权重和量化使用条件。该测试选择 FPGA 存储返回行为，并使用已有 AXI 通用时钟门控模型。`validation.json` 保存各项结果及实际设计文件摘要。

`run_storage_transition.py` 直接实例化实际的 `regfile` 和 `ia_ps_role_ram`，分别验证深度 32、128 的全部 16 个字节。观察行的地址可取任意值，并在一步更新前后保持相同；该行对应字节的初始内容相同，其余初始内容与功能输入自由。证明检查更新后内容仍相同，并检查读取该行时的同步返回，因此覆盖全部行、同址读写和连续访问。结果保存在 `storage_validation.json`。

全局访问许可的末级处理也通过 6 组完整命令与持续返回证明、32 项真实数组证明和 40,960 个真实数组比较周期；逐周期访问许可不受约束。`access_validation.json` 保存这一检查的完整源码与日志摘要。

完整 NPU 测试在 `SYNTHESIS` 和 `XILINX_FPGA` 配置下检查功能、容量边界、错误恢复、循环写回和三种分块布局。非紧凑输入配置包含 38 项功能、31 项容量、15 项写回与 12 项布局任务；紧凑配置根据合法输入复用范围生成 29 项容量任务，其余任务数量相同。两种配置均启用实际消费者和帧地址断言，共检查 4,314 次帧缓存槽选择。报告分别保存在 `production_validation.json` 与 `compact_validation.json`。

## 完整通道综合

配置为 7 个 8 KiB 存储块、预先选择 IA 写数据、配对 IA 端口与非空写请求。两次测量使用同一源码，分别关闭和开启返回选项。

| 资源或组合路径 | 关闭选项 | 开启选项 |
|---|---:|---:|
| 逻辑 LUT | 1,633 | 1,152 |
| RAMB36 | 26 | 34 |
| 触发器 | 10 | 10 |
| 最长寄存器间组合单元数 | 9 | 9 |

完整通道减少 481 个 LUT，增加 8 个 RAMB36。全局访问许可到独立端口存储使能只经过 1 个组合单元，到全部存储或状态端点最多经过 2 个组合单元。存储资源由普通 RTL 推断。映射使用 `physical-cost`、6667 ps 目标、300 ps 连线代价和最多 8 个输入的切割设置。此处记录结构映射结果，器件 150 MHz 的实现时序由完整设计布局布线分析确认。`measurement.json` 保存输入、映射文件和详细路径的摘要，`access_measurement.json` 记录访问许可路径的比较结果。

## 重复执行

在工程根目录执行：

```sh
python test/shared_role_ram/run_formal.py --out build/shared_role_commands
python test/shared_role_ram/run_memory.py --out build/shared_role_memory
python test/shared_role_ram/run_storage_transition.py --out build/shared_role_storage
python test/shared_ia_pairing/run_control.py --reference 19d62e18 --out build/shared_role_default
python test/shared_ia_pairing/run_control.py --reference 19d62e18 --paired --out build/shared_role_paired
python test/shared_role_ram/run_system.py --out build/shared_role_system --jobs 2
python test/shared_role_ram/prepare.py --out build/shared_role_inputs
```

`run_system.py --prepare-only` 生成消费者检查包装器，可传给已有生产回归的 `--verilator` 参数。综合输入可交给 `scripts/fpga/open_fpga_synth.py` 及 `remap_fpga_luts.py`，两种返回选项分别使用 `held` 与 `independent` case。

生产矩阵测试可使用以下入口：

```sh
python test/shared_role_ram/run_system.py --out build/shared_role_observer --prepare-only
python test/fpga_integration/run.py --out build/shared_role_production --verilator build/shared_role_observer/verilator_role --jobs 2
python test/shared_role_ram/collect_production_report.py --results build/shared_role_production --out build/shared_role_production_validation.json
```

紧凑输入配置使用同一个 FPGA 消费者包装器，编译参数只改变 `IA_COMPACT_ENABLE`：

```sh
python test/conv_npu/run.py --out build/shared_role_compact/npu --verilator build/shared_role_production/verilator_xilinx --jobs 2 --sizes 16 --bus-width 64 --cache-bytes 4096 --cache-line-bytes 128 --address-width 32 --vector-pe-count 8 --ps-storage-rows 799 --oa-s16-fifo-banks-max 4 --shared-bank-bytes 8192 --shared-bank-count 7 --ps-compress --force-raw --pool-bytes 49152 --ia-compact-enable 1
python test/ps_capacity_limits/run_npu.py --out build/shared_role_compact/capacity --sim build/shared_role_compact/npu/s16
python test/writeback_cyclic/run_npu.py --out build/shared_role_compact/output --sim build/shared_role_compact/npu/s16
python test/shared_role_ram/run_packed.py --out build/shared_role_compact/packed --sim build/shared_role_compact/npu/s16
python test/shared_role_ram/collect_production_report.py --results build/shared_role_compact --out build/shared_role_compact_validation.json
```
