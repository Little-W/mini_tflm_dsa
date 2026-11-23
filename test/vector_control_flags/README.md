# 向量算术与状态控制

`vector_engine_control` 负责解码向量操作。Hadamard 模式对应 `PE_MUL`，统一 `vector_pe` 在输入使能边沿为纯乘法保存零累加值。操作码、两个乘数和累加值在同一边沿接收，暂停期间共同保持。

`vector_engine_control_pkg` 将状态编码、握手资格、执行资格、窗口获取资格和权重读取资格组成同一个控制字。各状态更新同时保存这些字段。向量引擎的运行时检查逐周期比较状态资格与实际状态，并在纯乘法接收后检查 PE 已保存的操作码和零累加值。

舍入模块保留完整商、保护位和已舍弃位信息，使用最近偶数舍入。深度卷积、逐元素 Add、平均池化和 Softmax 由各自的数据有效信号使用统一的定宽算术模块。

## 验证入口

```bash
python3 test/vector_pe_accumulator/run.py --source-root . --out build/vector_pe_accumulator

python3 test/vector_engine/run.py \
  --source-root . --out build/vector_control_production \
  --pes 16 --tile 16 --jobs 1 \
  --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 \
  --bus-width 64 --window-lanes 16 --shared-storage \
  --shared-bank-bytes 8192 --shared-bank-count 7 --shared-ia-banks 2 \
  --check-weight-write-stage --rtl-assertions --stable-stimulus
```

算术检查覆盖全部 PE 操作编码、累加预选、位置参数、未知数据与使能暂停，并对实际控制源码的 16 种操作编码进行形式检查。系统检查使用独立整数参考，覆盖卷积、池化、INT8/INT16 向量运算、Add、Softmax、非对齐访问、尾通道、背压、取消、错误和恢复。输出目录保存配置、源码 SHA256、逐任务统计和完成摘要。
