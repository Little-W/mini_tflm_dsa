# 缓存请求吞吐与前端事务记录

测试通过只读绑定模块记录实际 `conv_windowed_cache` 和 `conv_im2col_frontend` 实例，使用共同存储算子入口检查全部计算输出。统计包括请求接收、请求处理、响应入队、响应消费的周期，以及这些事件之间的延迟分布。

`FRONTEND_TRANSACTION_TRACE` 保存每个周期的描述符输入、运行状态、请求地址、窗口索引、纪元、释放位置、进度、取消资格和输出握手。`compare.py` 分别比较完整周期记录和按接收顺序排列的请求元数据。队列容量、请求寄存和响应寄存沿用被测源码中的配置。

## 运行

使用 Verilator 5.054，并把上传性能环境中的共同工作负载目录、参考支持目录传给测试入口：

```bash
python3 test/cache_throughput/run_operator_profile.py \
  --repo "$REPO" --reference-root "$REFERENCE_SUPPORT" --out "$RESULT" \
  --verilator "$VERILATOR" --jobs 1 \
  --bank-bytes 4096 --bank-count 9 --cache-bytes 65536 --pe-count 16 \
  --synthesis --fpga --workloads "$WORKLOADS" --ar-min-interval 1 \
  --plusarg CONV_FRONTEND_PROFILE --plusarg CACHE_THROUGHPUT_PROFILE \
  --plusarg FRONTEND_TRANSACTION_TRACE \
  --cases dw3x3_s1_48_c8 conv3x3_32_c16_o16
```

两次运行使用相同的输入文件后，可以进行完整周期比较：

```bash
python3 test/cache_throughput/compare.py \
  --reference "$REFERENCE_RESULT" --current "$CURRENT_RESULT" \
  --out "$COMPARISON" --expect-equal
```

不指定 `--expect-equal` 时，脚本报告第一次不同的周期及请求字段，适用于比较允许改变请求时机的实现。

## 固定配置结果

以下运行均采用 16 个计算单元、16 条窗口通道、64 KiB 缓存、128 字节缓存行、2 个未完成需求请求，输入、初始内存和预期输出文件的 SHA256 完全相同。两项算子的全部数值检查均通过。

| 生产源码 | 深度卷积 `dw3x3_s1_48_c8` | 普通卷积 `conv3x3_32_c16_o16` |
|---|---:|---:|
| `744315bb` | 30,165 周期 | 28,092 周期 |
| `e4415016` | 32,882 周期 | 28,092 周期 |
| `e4415016` 配合 `744315bb` 的缓存模块 | 32,882 周期 | 28,092 周期 |

固定 `e4415016` 的其他模块后，两种缓存实现的 60,996 个前端周期记录、缓存延迟分布和取消次数完全相同。比较完整 `744315bb` 与 `e4415016` 时，深度卷积的 13,348 次缓存请求包含完全相同的地址及元数据序列；第一次时间差异出现在第 493 个周期的前端描述符输入。普通卷积的 28,103 个完整前端周期记录完全相同。

在 `e4415016` 中，普通卷积的 8,836 次请求有 8,308 次使用预读快照，8,298 次在接受后 1 个周期返回，前端没有请求接收停顿。深度卷积的 13,348 次请求有 2,893 次使用预读快照，10,362 次在接受后 2 个周期返回。这些记录用于区分缓存处理能力、预读准备时间和前端请求间隔。
