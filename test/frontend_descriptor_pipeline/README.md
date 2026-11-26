# 卷积前端准备阶段检查

生产 DMA 为卷积前端启用描述符准备寄存和行地址准备寄存。准备阶段保存描述符和行地址，使提交阶段能够共用坐标与地址运算。

## 生产配置读取

`test/gemmini_comparison/run_storage_operators.py` 从 `axi_dual_block_dma.sv` 的唯一 `u_frontend` 实例读取 `REGISTER_DESCRIPTOR`、`REGISTER_ROW_ADDRESS`、`REGISTER_CACHE_REQUEST` 和 `CACHE_RESPONSE_DEPTH`。三个寄存参数必须显式连接为布尔常量，响应容量必须为正的二次幂。仿真程序输出四个实际参数，并与读取值及缓存容量配置逐项比较。

## 周期比较模式

`test/timing_operator_regression/run.py` 的默认模式要求硬件配置、输入集合和输出内容相同，且每个算子的周期数不增加。

显式使用 `--allow-preparation-stage-change` 时，允许 `conv_register_descriptor` 与 `conv_register_row_address` 两个字段变化。其余硬件字段仍必须相同，62 项算子必须全部完成，输入和输出摘要仍须相同。比较报告保留完整配置差异、每个算子的周期差、总周期差、增加和减少周期的算子数量。`timing_result` 单独报告是否存在周期增长。参照文件未记录的字段通过 `reference_recorded` 标明。

`--allow-cache-response-depth-change` 允许单独比较响应容量的变化。两个选项可同时使用；报告列出允许变化的全部字段，其余存储容量、计算并行度和仿真条件仍须相同。

运行参数解析与比较策略检查：

```sh
python3 test/frontend_descriptor_pipeline/check_operator_profile.py \
  --out build/frontend_descriptor_pipeline/operator_profile_checks.json
```

32 项检查覆盖显式参数读取、注释排除、缺失或重复参数、动态表达式、严格比较、准备阶段和响应容量变化、周期差统计，以及存储容量、缓存请求寄存、输入、输出和任务数量检查。

使用保存的输入运行生产算子：

```sh
python3 test/timing_operator_regression/run.py \
  --repo . --out build/frontend_descriptor_pipeline/operators \
  --inputs-from /path/to/reference/inputs \
  --compare-with /path/to/reference \
  --allow-preparation-stage-change --allow-cache-response-depth-change --jobs 1
```

## 2026-11-26 生产算子结果

`production_comparison_20261126.json` 保存 62 项算子的逐项结果、硬件参数、输入摘要和仿真程序摘要。生产配置使用 16×16 阵列、64 位 AXI、7 个 8192 字节共享存储块、4096 字节卷积缓存及 8 个向量计算单元。

全部 62 项数值结果与参照版本相同。描述符和行地址准备阶段启用后，总周期由 581389 增至 656243，增加 74854 个周期，增幅约 12.87%。51 项周期相同，11 项周期增加。报告将功能检查结果与周期变化分别列出。

`cache_response_validation.json` 保存提交 `bf0e8740` 使用两项缓存响应时的检查。62 项算子全部通过，总周期为 797959，51 项与检查点相同，11 项增加；每项输出摘要均与检查点一致。独立前端连续请求测试完成 42 项任务，缓存协议测试覆盖 12 类场景，两项请求可同时在途，连续热命中的接收与返回间隔均为一个周期。
