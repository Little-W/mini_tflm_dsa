# 矩阵偏置保存验证

`npu_matrix_engine` 保存最近返回的偏置和当前计算使用的偏置快照。两组寄存器共用偏置来源选择与同步清零数据，各自保留写入使能和异步复位。因此，偏置返回、计算启动和配置清零的同周期组合均保持原有状态转换。

`run.py` 从实际矩阵引擎文件中逐字提取修改区域，在相同端口包装下比较两份实现。形式检查保留全部自由输入，证明偏置历史与计算快照的所有位在每个周期相同。四态仿真覆盖 `p_size=1、3、16、32`，包含 `X/Z` 数据、资格信号和复位输入；测试在时钟和复位边沿前稳定数据，比较边沿前后的完整状态。

```sh
python test/matrix_bias_storage/run.py --out build/matrix_bias_storage/validation
python test/matrix_bias_storage/prepare_measurement.py --out build/matrix_bias_storage/measurement
python scripts/fpga/open_fpga_synth.py --case-config build/matrix_bias_storage/measurement/cases.json --cases reference current --out build/matrix_bias_storage/synthesis
```

生产尺寸的独立偏置寄存区域包含两组 `16×32` 位存储。同一开源综合流程中，共享数据选择使逻辑 LUT 从 1,024 个降至 514 个，触发器保持 1,024 个，寄存器之间最长组合路径保持 1 级。完整矩阵引擎和 SoC 的资源数量由各自的完整连接综合结果统计。
