# DMA 启动与错误恢复检查

DMA 读仲裁器按当前所有者生成各客户端的接收信号，`rd_dma_start` 为这些接收信号的并行或运算。描述符选择与启动事件同时计算，错误终止、输出空间和客户端请求仍参与实际接收条件。

## 启动表达式

`run_start_formal.py` 提取当前 RTL 与参考提交 `dde5e7c9` 的授权、接收和启动表达式，比较全部十个输入位的组合关系。量化客户端开启和关闭两组参数均已通过，无输入假设。

```bash
python test/dma_abort_boundary/run_start_formal.py \
  --reference dde5e7c9 --out build/dma_start_formal
```

## 在途事务计数

三个计数位分别根据启动、完成和取消事件计算翻转条件。所有事件组合均保持原三位计数器的模八运算，包括完成与取消同时有效时减二，以及三个事件同时有效时减一。

`run_count_formal.py` 从实际 RTL 提取计数更新关系，与参考提交的状态分支比较。证明覆盖三个状态位和三个事件位的全部 64 种输入组合，不限制当前计数值。

```bash
python test/dma_abort_boundary/run_count_formal.py \
  --out build/dma_pending_count_formal
```

## 实际 DMA 事务

`run.py` 连接真实仲裁器、双通道 DMA、前端和缓存。16 个场景覆盖两个所有者下的八类事务边界，检查不同接收进度下的错误终止、并发请求和恢复任务。每个场景均要求原任务正确结束，并完成后续恢复任务。

```bash
python test/dma_abort_boundary/run.py --out build/dma_abort_boundary
```

当前 16 个场景均已通过。摘要记录实际输入源码、编译与执行命令、二进制 SHA256 和每个场景结果。

`--source-root` 可指定完整 SoC 综合使用的固定 RTL 目录，测试程序与参考行为保持一致。

## 错误响应与命令接收

选择寄存错误上报时，有效的 `RRESP` 或 `BRESP` 错误立即停止接收新命令。该条件直接读取响应有效位和错误位，独立于 `RREADY`、`BREADY`。已接收事务的中止使用真实响应握手；公开错误状态在下一周期上报。活动写通道保持原有数据接收周期，已经进入写缓冲的数据按接收顺序发送。

`check_error_admission.py` 提取实际 RTL 的错误生成过程，证明两种上报模式下的命令接收、活动事务中止及错误状态周期。功能输入不受限制，包含有效错误响应受到背压的情况。证明包含复位起始状态和无界归纳检查。

```bash
python test/dma_abort_boundary/check_error_admission.py \
  --out /tmp/dma_error_admission
```

事务测试分别统计源端接收和外部 AXI 接收，并逐拍比较写缓冲输入与外部写数据、字节使能及末拍标记。24 个场景包含两个写入所有者下的响应错误、外部中止、同周期读错误与写接收、等待响应、准备阶段中止、准备阶段复位和后续任务恢复。当前 32 位通用配置及 64 位生产配置均通过全部场景，并启用 RTL 断言和未定义行为检查。参考版本同样通过 32 位配置的 24 个场景。

```bash
python test/dma_abort_boundary/run.py --out /tmp/dma_error_bus32 \
  --jobs 1 --bus-width 32 --prepare-abort
python test/dma_abort_boundary/run.py --out /tmp/dma_error_bus64 \
  --jobs 1 --bus-width 64 --size 16 --dma-size 16 --cache-blocks 64 \
  --data-width 16 --outstanding 4 --fpga --prepare-abort
```

`error_admission_validation.json` 保存源代码摘要、形式证明、每个事务场景结果以及两种参数配置。
