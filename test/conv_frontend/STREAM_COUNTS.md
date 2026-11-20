# 前端剩余列数寄存

`conv_im2col_frontend` 在描述符接收时保存整行剩余列数和有效剩余列数。每次接受写入后减去实际写入的通道数，开始下一行时恢复对应的整行计数。填充写入同样推进计数，保留 `TILE_COUNT_W` 位无符号减法的回绕行为。

两个计数分别保持 `col_remaining = cols_q - col_idx` 和 `active_remaining = active_cols_q - col_idx`。通道选择、末列检查和流式请求直接读取计数。配置与复位优先级、描述符接收、缓存请求和公开输出周期保持一致。

## 功能检查

参考提交为 `2f06471c1b4647d406026a4caadb6ba60b140859`。四组完整层次形式比较包含真实前端、缓存、预测器和 AXI 读控制，输入不施加额外限制，共通过 108,611 位状态与输出比较。参数覆盖 `SIZE=4/8/16`、`LANES=1/2/4`、`BUS_WIDTH=32/64` 以及四种缓存策略。

独立数值测试采用 `LANES=2`，完成四组、148 项任务，比较全部 19 个公开输出，共 1,747,244 个周期。控制测试另完成 23 项检查与 134 个比较周期。

## 独立综合

前端采用 `SIZE=16`、`LANES=2`、`BUS_WIDTH=64`、128 个集合和两路缓存，缓存与预测器在独立测量中作为接口。XC7 原生映射得到 6,531 个逻辑 LUT、3,238 个触发器、30 个 DSP48E1 和 724 个 CARRY4。最长内部组合路径为 21 个单元，完整连接图检查通过。

完整 SoC 使用自己的 DSP 分配、LUT 成本和布局步骤；其资源与最长路径单独测量。

## 运行

```sh
python3 test/conv_frontend/tools/run_state_equivalence.py --reference-ref 2f06471c --out build/frontend_counts/formal
python3 test/conv_frontend/tools/compare_frontend.py --reference-ref 2f06471c --lanes 2 --verilator verilator-modern --out build/frontend_counts/interface
python3 test/conv_frontend/tools/synthesis.py --lanes 2 --out build/frontend_counts/synthesis
python3 test/conv_frontend/tools/measure_descriptor_paths.py --mapped build/frontend_counts/synthesis/mapped.json --pre-lut build/frontend_counts/synthesis/pre_lut.il --out build/frontend_counts/paths.json
```

资源、参数、完整状态比较与逐周期结果保存在 `docs/data/frontend_stream_counts_validation.json`。
