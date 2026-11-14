# 数据流分析

`dataflow_sim/analysis/` 保存分块复用、计算时间估计、参数搜索及绘图程序。分析采用脚本内的阵列、存储和时间假设，适用于设计空间探索；具体硬件周期应通过 RTL 仿真测量。

## 环境与运行

```bash
python3 -m pip install -r dataflow_sim/requirements.txt
mkdir -p build/dataflow_sim
cd build/dataflow_sim
python3 ../../dataflow_sim/analysis/compare_methods.py
```

从输出目录运行绘图或扫描脚本，可将其生成的图片和日志保存在该目录。`mem_opt_dynamic_size4.py` 提供动态工作组搜索，`speedup_analysis_s16.py` 和 `scan_tile_compute_time.py` 使用该模块进行统计和参数扫描。`opt_calc_mcu_int.py` 包含定点计算和 C 代码生成程序。运行前可在脚本中调整数据规模和绘图参数。
