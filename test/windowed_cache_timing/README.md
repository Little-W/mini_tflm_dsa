# 窗口缓存时序与算术验证

窗口缓存的有效位与同步标签在同一时钟边沿保存。同周期写入通过显式转发参与该边沿的捕获，后续命中判断使用保存结果。请求容量、快照身份、替换资格和填充冲突分别计算；地址比较按三位分组并行完成。配置末地址、预取代次和请求长度采用完整位宽的行为级算术，由综合工具推断算术资源。

`conv_axi_span_reader` 分别准备页末长度与请求长度的 AXI `ARLEN` 编码，截短条件在最后选择编码。非整字起点、跨页、窄读取、返回错误和连续请求的状态转换均保持原有周期。

## 资源与路径

独立综合参数为 `SETS=16`、`WAYS=2`、`LINE_BYTES=128`、`BUS_WIDTH=64`、`READ_WIDTH=64`、`DEMAND_DEPTH=2`、`CACHE_POLICY=3`、`p_defer_retire_shift=1`。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,403 | 3,288 |
| LUTRAM 占用的名义 LUT | 420 | 420 |
| 名义 LUT 总数 | 3,823 | 3,708 |
| 触发器 | 2,447 | 2,461 |
| DSP | 15 | 21 |
| RAMB18 | 9 | 9 |
| CARRY4 | 58 | 31 |
| 最长寄存器间组合路径 | 12 | 11 |

两份连接图均完整。组合级数包含真实连通的 LUT、进位、异步存储读取及 DSP 算术段。上述数据来自开源映射流程；目标器件上的 150 MHz 时序由布局布线后的时序报告确认。当前独立模块仍有 11 级路径。

## 验证范围

| 检查 | 参数与范围 | 结果 |
| --- | --- | ---: |
| 窗口缓存完整状态证明 | 4 组，覆盖深度 1、2、4，32/64 位总线及生产参数 | 99,536 位通过 |
| AXI 分段读取完整状态证明 | 54 组，总线 32～1,024 位，请求长度 1～65,535 字节 | 28,032 位通过 |
| 缓存控制与有效位四态检查 | 5 组，包括每个输入位置的未知值与高阻态 | 5,046,290 次通过 |
| 填充资格和长度算术四态检查 | 3 组 | 897,030 次通过 |
| 页末长度编码四态检查 | 7 组，检查全部 4 KiB 页内地址 | 1,518,592 次通过 |
| 独立存储模型数值仿真 | 深度 1、2，各 12 个场景 | 24 个场景通过 |
| 前端持续请求仿真 | 16 通道阵列、64 位总线、8 个读取通道，窗口模式关闭和开启 | 84 个任务及 23 项控制检查通过 |

完整状态证明使用不受限制的输入，逐周期检查全部存储状态、控制状态、外部输出和实际消费者。有效位原始组合读取地址及直接输出允许在同步边沿内重排，因此这四类原始端口名称不作为匹配对象：`valid_i_rd_addr`、`u_valid.i_rd_addr`、`valid_o_rd_data`、`u_valid.o_rd_data`。有效位存储内容、捕获寄存器及其消费者仍参与完整证明。

数值仿真覆盖持续命中、返回背压、同组替换、范围错误、填充错误恢复、预取、配置排空、复位取消和非整字旁路。深度 1、2 的持续命中接收间隔和返回间隔均为一个周期。前端检查独立计算卷积元素值，并检查顺序、两项在途容量和错误恢复。

## 运行

从仓库根目录执行：

```sh
python3 test/windowed_cache_timing/run_formal.py
python3 test/windowed_cache_timing/run_four_state.py
python3 test/windowed_cache_timing/run_control_four_state.py
python3 test/windowed_cache_timing/run_span_four_state.py
python3 test/span_page_clip/run_formal.py --reference-ref 0097b66ed57e1b8ef00e402e89dc5b274f1626be --out build/windowed_cache_timing/span_formal
python3 test/cache_pipeline/run.py --fpga --bus-width 64 --read-width 64 --line-bytes 128 --cache-bytes 4096 --profiles 1:2 2:2 --jobs 1 --out build/windowed_cache_timing/numeric
python3 test/conv_frontend/tools/run_numeric.py --fpga --sizes 16 --continuous --out build/windowed_cache_timing/frontend
```

所有新增脚本接受 `--source-root` 和 `--out`。完整状态证明还接受 `--reference-root`、`--reference-ref` 和参数列表。工具包括 Python、Pyosys 及其 Slang 前端、Icarus Verilog 和 Verilator。`validation.json` 保存源码散列、参数、检查数量及详细报告的位置与散列。
