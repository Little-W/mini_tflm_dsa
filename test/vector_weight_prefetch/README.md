# 共享权重预取验证

向量引擎在处理当前核位置时，向共享 RAM 请求下一核位置。当前行的 128 位数据与核位置一起保存，返回数据携带同步请求地址。输入等待和多组通道发射可继续使用已保存的数据；下一核位置第一次发射可以直接使用同步返回的数据。

`observer.sv` 通过 `bind` 观察真实向量引擎，独立记录实际共享 RAM 请求地址和权重写入内容，检查以下行为：

- 返回地址和完整 128 位数据对应实际请求。
- 缓存行对应已接收的权重写入内容。
- 每次 DW 发射使用当前核位置的权重。
- 输入等待、跨核位置推进、无效坐标跳过均有覆盖。
- 任务开始、输出初始化、通道块切换和异常状态清理缓存有效位。
- 权重加载与权重读取在向量引擎中分配到不同周期。

完整功能测试继续使用现有独立整数参考实现和逐通道权重检查。`compare.py` 比较每个用例的全部统计字段，包含总周期、计算周期、DMA 等待、读写字节数以及窗口响应统计。

## 运行功能检查

```sh
python test/vector_engine/run.py \
  --source-root /absolute/path/to/candidate \
  --out build/vector_prefetch_fpga \
  --bus-width 64 --pes 8 --shared-storage --shared-quant \
  --xilinx --check-weight-prefetch --jobs 1
```

通用 RTL 路径使用 `--bus-width 32` 并省略 `--xilinx`。比较时，两次运行应采用相同配置和同一组其他模块源码：

```sh
python test/vector_weight_prefetch/compare.py \
  --reference build/vector_reference/summary.json \
  --candidate build/vector_prefetch_fpga/summary.json \
  --out build/vector_prefetch_fpga/cycle_comparison.json
```

共享存储器的同地址读写冲突、错误处理与配置恢复由专用测试覆盖：

```sh
python test/vector_shared_store/run.py \
  --out build/vector_prefetch_shared_store \
  --profiles 2048:7:1:1 2048:7:1:0 --cycles 2000 --jobs 1
```
