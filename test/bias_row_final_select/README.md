# 偏置行索引与组状态

`npu_output_pipeline` 并行计算偏置行索引的保持、递增和回绕结果，使用普通条件表达式选择组首清零。行索引使用独立的 `always_ff`，采用 `rst_n` 的异步低有效复位。

偏置组基址、末组基址、末组行数、当前有效行数和待生效有效行数按各自状态条件更新。读取索引与行索引更新共用扩展差值产生的回绕条件。当前实现及其验证结果见 [偏置行边界计算](../bias_row_distance/README.md)。

## 测试入口

`extract_control.py` 从实际输出模块提取完整偏置控制区域，将端口和参数名称转换为独立验证模块的名称，保留生产接口中三十二位 `i_exec_m` 的宽度。声明、组地址计算、读取索引和两个时序过程均取自实际源码。

`run_formal.py` 比较完整状态和公开输出，同时覆盖 FPGA 与通用配置。默认参考版本为仓库中的 `ca34494`，`--reference` 可指定其他版本；读取器同时支持独立输出模块和包含偏置控制的顶层文件。`run_npu.py` 使用完整 NPU 执行 WS、IS 和错误恢复数值测试。

```sh
python3 test/bias_row_final_select/run_formal.py \
  --out build/bias_row_final_select/formal
python3 test/bias_row_distance/run.py \
  --out build/bias_row_final_select/row_distance
python3 test/bias_row_final_select/run_npu.py \
  --out build/bias_row_final_select/npu --verilator verilator --size 4 --jobs 1
```

`prepare_measurement.py` 和 `measure_paths.py` 可生成并分析两个指定版本的独立模块映射。输入端口只在路径分析图中标记为起点，实际硬件没有因此增加寄存器或周期。

```sh
python3 test/bias_row_final_select/prepare_measurement.py \
  --out build/bias_row_final_select/inputs
```

当前入口验证见 `entry_validation.json`：16 组参数的完整控制等价检查通过，
共证明 7,044 位等价关系；行边界四态测试完成 30,000 组输入和 3,030,000 位输出比较。
