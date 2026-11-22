# 独立卷积模块验证

`rtl/npu/conv/` 每个文件只定义一个模块。算术使用统一的定宽普通 RTL，输入寄存、通道宽度、存储深度、同步读取和写回合并能力由功能参数决定。

## 算术与存储

```bash
python3 test/conv_portable/run.py --out build/conv_portable/arithmetic_modules
```

四项全输入形式检查分别验证：

- `vector_read_address_add` 的 32 位基地址、32 位偏移和 16 位通道的完整 34 位和。
- `vector_reduce_alu` 的 INT32 模加法、极大值、极小值及同时选择时的极小值优先关系。
- `vector_coordinate_bound` 的 34 位有符号坐标和 16 位尺寸范围。
- `vector_interval_bound` 的 17 位有符号半开区间。

权重测试同时实例化异步字节读取和同步整行读取模块，以独立数组保存期望内容。检查完整写入、字节掩码、同地址读写、越界地址、未知使能与 `X/Z` 数据。深度/通道配置为 `1/1`、`7/4`、`49/16`、`49/32`，共 160,212 次四态比较。同步读取检查写入前内容，异步读取检查写入后的当前内容。

## 流水与协议

`test/vector_scalar_dsp_pair` 检查四种输入寄存组合及暂停行为，`test/vector_scalar` 检查完整 INT64 数值。`test/vector_extremum` 比较完整寄存乘加与极值运算。`test/vector_softmax` 检查累加器和 Softmax 数值。`test/vector_banked_writeback` 检查写请求接收、字节地址、随机等待、持续发送、取消与错误恢复。

前端配置共享、描述符排队、范围和随机背压测试位于 `test/frontend_pipeline` 与 `test/frontend_group_feedback`。

## 生成综合输入

```bash
python3 test/conv_portable/prepare_measurement.py \
  --pes 16 --out build/conv_portable/measurement_inputs
```

生成的 `cases.json` 包含寄存 PE 阵列、完整向量引擎、归约单元、地址加法与标量乘法器。各项按真实模块依赖展开源文件，`manifest.json` 保存文件 SHA256。资源数量和组合路径由后续综合结果报告。
