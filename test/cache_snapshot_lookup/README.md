# 缓存读取组号与标签比较

`conv_windowed_cache` 在标签和数据读取边沿保存 `lookup_snapshot_set`。命中资格要求当前请求组号与这一寄存值相等，因此有效位存储的查询端口可以直接使用保存的组号。工作请求和等待填充的请求分别比较标签，前景状态在比较结果之间选择。

该组织保留请求接收周期、返回周期、预取次序、配置清除、错误返回和全部存储容量。有效位存储的其余读取端口以及写入端口保持原有行为。

## 完整状态证明

```sh
python test/cache_snapshot_lookup/run_formal.py \
  --reference-ref 9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a \
  --out build/cache_snapshot_lookup/formal
```

脚本先核对源码差异仅包含读取组号和标签比较这两处，再比较整个缓存的寄存状态、存储内容和公开输出。外部输入保持自由。内部异步读取信号在未取得命中资格时可以不同，验证不把这些信号作为独立的等价比较点；其使用结果和完整存储内容均参与证明。

10 组配置覆盖 1、2 路缓存，1、2、4 个在途需求名额，8～256 字节缓存行，32、64 位总线，以及 128 组生产配置和 256 组配置。合计证明 172,428 位等价关系。

## 协议与数值检查

```sh
python test/cache_snapshot_lookup/run_protocol.py \
  --verilator verilator-modern \
  --out build/cache_snapshot_lookup/protocol
```

入口按顺序运行既有 `test/cache_pipeline/run.py` 的四种配置，并在各配置完成后清理编译中间文件。原有警告检查、协议断言及数值比较保持启用。

48 个场景覆盖缺失请求、连续命中、响应背压、冲突替换、范围错误、填充错误恢复、预取接收和恢复、配置排空、复位取消、旁路字节读取以及几何提示次序。四种配置共接收 761 项请求，返回 750 项，并在复位时取消 11 项。连续命中时，请求接收和响应返回间隔均为一个周期。

## 原生 RTL 综合

```sh
python test/cache_snapshot_lookup/measure.py \
  --reference-ref 9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a \
  --out build/cache_snapshot_lookup/measurement
```

使用相同公共 RTL 和参数执行 Yosys Xilinx 7 系列综合。生产缓存参数为 128 组、2 路、16 字节缓存行、64 位总线和 4 个在途需求名额，算术使用普通 RTL 推断。

| 资源 | 修改前 | 当前实现 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 3,739 | 3,584 | −155 |
| FF | 1,800 | 1,807 | +7 |
| RAMB18 | 25 | 25 | 0 |
| 分布式存储 LUT 位置 | 256 | 256 | 0 |
| DSP | 0 | 0 | 0 |
| 最长组合路径级数 | 13 | 13 | 0 |

局部最长路径位于 `conv_axi_span_reader` 的突发长度准备逻辑，当前结果仍超过 9 级目标。`measurement.json` 保存完整状态证明、协议检查和这次原生 RTL 测量的摘要；真实器件 LUT 使用量和 150 MHz 时序由 Vivado 报告检查。
