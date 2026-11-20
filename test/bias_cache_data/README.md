# 偏置缓存数据源选择

`bias_loader_buffer` 在 WS 模式下准备完整偏置向量。DMA 装载阶段从 `write_data` 写入缓存，驻留数据读取阶段从 `read_data` 写入缓存。各数据对共用一个 64 位数据源选择器，仍按原有的逐字节使能和数据对编号更新寄存器。

实际控制器保证 DMA 装载期间 `ws_response_valid` 为零。形式验证先对该控制逻辑进行时序归纳，再使用这一已证明的性质，检查每个缓存数据位在任意数据、地址和使能输入下的下一状态。两份源码中的控制、存储接口及公开输出逻辑同时按完整文本比较。

## 资源与周期

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=28`、`GROUP_BLOCKS_MAX=32`。比较提交为 `d8fb9581`，两份源码使用相同的 Xilinx 7 系列模块综合流程。

| 项目 | 比较版本 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT 原语 | 1,133 | 621 |
| 触发器 | 769 | 769 |
| RAMB36E1 | 1 | 1 |
| DSP48E1 | 0 | 0 |
| CARRY4 | 51 | 51 |
| 最长寄存器间组合路径 | 11 | 11 |

模块减少 512 个逻辑 LUT。生产数据存储容量保持 32,768 位，WS 向量缓存保持 512 位。全部 392 个偏置加载任务的 DMA 命令数和周期数与比较版本相同，合计 193,571 个周期。

## 验证范围

形式验证覆盖 4 组尺寸、总线宽度、计数宽度和分组容量。每组包含实际控制器的无限时序归纳以及逐位缓存下一状态检查。复位后不限制外部输入；初始化、装载启动、模式切换、完成通知及数据输入均可任意变化。缓存更新检查使用的阶段互斥条件由前一项实际控制器证明提供。

数值测试覆盖 WS/IS、32 位与 64 位总线、驻留命中、预取、参数尾部和多次复用，并与相同测试的比较版本核对每个任务的命令数及周期数。

```sh
python3 test/bias_cache_data/run_formal.py --out build/bias_cache_data/formal
python3 test/bias_loader_reuse/run.py --out build/bias_cache_data/reuse
python3 test/bias_loader_range/synthesis.py --out build/bias_cache_data/native_current
python3 test/bias_loader_range/synthesis.py --reference-ref d8fb9581 --out build/bias_cache_data/native_reference
```

完整配置、源文件摘要、资源统计和验证结果保存在 `measurement.json`。
