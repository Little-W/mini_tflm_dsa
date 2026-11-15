# 可选 operand cache 的任务退休回归

本目录仅保留当前生产 RTL 的可执行回归源码。输入、描述符、参考值都由 SV 过程
即时生成，不依赖旧 RED/GREEN 结果、源码快照或内存文件。默认输出为
`build/conv_dma/operand_drain/`。

## 固定场景

首任务是 s8 GEMM `k=1,n=16,m=1`，无 bias、per-tensor 量化，两个 operand 都以
64 B 对齐且行 stride 为 64 B。可选外层 cache 按 64 B 分配；首四个 weight R beat
已满足计算需求后，测试暂停剩下 12 个 R beat，同时允许 OA 写通道继续完成。

AXI-Lite wrapper 没有公开可选 cache 参数，因此测试用 `defparam` 启用真实
`OPERAND_CACHE_ENABLE`，并将 core 的 `cfg_operand_fetch64` 输入 force 为 1。
cache、DMA、controller、AXI-Lite 和时钟门控均是生产 RTL，没有用替代数据通路。

内部计算/OA 完成后再保持尾部 250 周期，要求外部 DONE/READY 保持为 0，没有
新任务/flush/bypass 变化，core 时钟仍有效；额外 START 被拒绝。释放尾部后只
允许一次完成握手。随后运行真正的原图 IS Conv，再将同地址 A/B 换值执行 GEMM。
三个任务之间验证真实 clock gate 关闭并重新唤醒；六个输出字节与直接计算值比较。

这个测试保护 `operand_read_cache.idle` 到 top 任务退休和 abort drain 的合同，
不需要重新执行旧缺陷版本来判断当前 RTL 是否正确，也不计入 CPU 固件性能测试。

```sh
python3 test/conv_dma/operand_drain/run.py \
  --out build/operand_drain --verilator verilator
```

`build.json` 记录所有 RTL、testbench 和 `.svh` include 哈希。可用 `--skip-build`
复用同目录构建；可选 `--reuse-build-root` 允许使用另一处本地构建。源列表不完整或
哈希不同会拒绝复用。运行输出、完整日志和 `summary.json` 都写入本次 `--out`。
