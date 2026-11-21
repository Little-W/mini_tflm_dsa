# 偏置行索引与组状态

`npu_top` 并行计算偏置行索引的保持、递增和回绕结果，使用普通条件表达式选择组首清零。行索引使用独立的 `always_ff`，保持 `core_rst_n` 的异步低有效复位和原有采样边沿。

偏置组基址、末组基址、末组行数、当前有效行数和待生效有效行数按各自状态条件更新。读取索引与行索引更新共用扩展差值产生的回绕条件。当前实现及其验证结果见 [偏置行边界计算](../bias_row_distance/README.md)。

## 测试入口

`extract_control.py` 从实际顶层提取完整偏置控制区域。`run_formal.py` 比较完整状态和公开输出，同时覆盖 FPGA 与通用配置。`run_npu.py` 使用完整 NPU 执行 WS、IS 和错误恢复数值测试。

```sh
python3 test/bias_row_final_select/run_formal.py \
  --reference cfcc1a95 --out build/bias_row_final_select/formal
python3 test/bias_group_index/run_formal.py \
  --reference-rev cfcc1a95 --out build/bias_row_final_select/group_index_formal
python3 test/bias_row_final_select/run_npu.py \
  --out build/bias_row_final_select/npu --verilator verilator --size 4 --jobs 1
```

`prepare_measurement.py` 和 `measure_paths.py` 可生成并分析两个指定版本的独立模块映射。输入端口只在路径分析图中标记为起点，实际硬件没有因此增加寄存器或周期。
