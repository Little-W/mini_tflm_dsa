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
