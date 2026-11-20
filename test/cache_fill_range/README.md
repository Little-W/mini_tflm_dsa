# 缓存填充上界计算

`conv_windowed_cache` 根据已保存的 `bypass_q` 选择需求地址或缓存行地址，再共用上界加法与范围比较。加法使用 33 位结果，完整保留地址末端的进位。`fill_end` 仍在 `F_IDLE` 或当前填充成功的时钟边沿采样。

普通缓存填充和旁路填充分别使用 `LINE_BYTES` 与 4 字节长度。两个模式的地址选择、范围截取和寄存器更新组合在相同边沿完成，接口、请求顺序、响应周期和全部存储容量保持一致。仿真断言独立检查选择级的范围。

## 资源比较

参考提交为 `f761c3a7`。独立综合固定 `SETS=128`、`WAYS=2`、`BUS_WIDTH=64`、`LINE_BYTES=16`，启用 `XILINX_FPGA`，使用同一版 Yosys `synth_xilinx`、公共 RTL 和综合选项。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,662 | 3,449 |
| 分布式 RAM 的 LUT 位置 | 276 | 276 |
| 合并前逻辑与存储 LUT 总计 | 3,938 | 3,725 |
| 触发器 | 1,832 | 1,832 |
| RAMB18E1 | 24 | 24 |
| CARRY4 | 117 | 106 |
| 最长组合单元序列 | 14 | 13 |

该模块独立映射减少 213 个逻辑 LUT。完整 SoC 的 LUT 位置和组合路径由统一综合与物理布局统计。

## 功能验证

实际 FPGA 分支的三个配置通过完整模块形式等价比较，共 97,629 个位。公开输出、对应寄存状态和存储内容均参加比较，外部输入无附加约束。

| 缓存组数 | 路数 | 总线位宽 | 缓存行字节数 | 已证明相等的位数 |
| ---: | ---: | ---: | ---: | ---: |
| 128 | 2 | 64 | 16 | 78,860 |
| 2 | 1 | 32 | 8 | 4,353 |
| 2 | 2 | 64 | 256 | 14,416 |

实际窗口 DMA 的当前实现和参考实现均通过 422 次请求接收、418 次完成、4 次复位取消及 4,457 个数据值比较。测试覆盖连续命中、普通请求与窗口请求并发、随机坐标、背压、错误响应、配置等待、无效描述及复位恢复。两次运行的连续请求周期记录逐字节相同。

源文件摘要、完整形式比较结果、DMA 运行记录及资源结果保存在 [measurement.json](measurement.json)。

```sh
python3 test/frontend_rtl_structure/formal.py \
  --reference f761c3a7 --cases cache128 cache_line8 cache_line256 \
  --out /tmp/cache_fill_end_formal
python3 test/window_dma/run.py --reference-ref f761c3a7 \
  --fpga --verilator verilator-modern --jobs 1 \
  --out /tmp/cache_fill_end_numeric
python3 test/cache_storage/synthesis.py --fpga \
  --out /tmp/cache_fill_end_current
```

重复参考实现的资源测量时，将参考提交中的 `conv_read_cache.sv`、`conv_sdp_ram.sv`、`conv_axi_span_reader.sv` 和 `regfile.v` 放入同一目录，并通过 `synthesis.py --reference` 指定该目录。
