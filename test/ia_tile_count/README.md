# IA 配置分块数验证

`ia_loader` 根据全局归约长度、当前输入长度和已保存长度选择取整来源。分块数由移位后的整数部分加上余数资格得到，八位分组前缀并行形成各组进位，并在原配置边沿保存结果。

`run.py` 直接提取生产 RTL 的来源选择与完整定宽算术，证明所有输入位的结果相等。检查覆盖 7、16、17、32、64 位数据以及不同块尺寸，输出包含最高进位。每组参数还执行 41,536 次四态比较，覆盖零值、上边界、不同状态和 `X/Z` 输入。

完整 IA 验证继续使用现有参数化时序证明和逐周期接口比较，检查预取、顺序访问、分组复用、数据输出及停顿行为。

```sh
python test/ia_tile_count/run.py --out build/ia_tile_count/arithmetic
python test/ia_optimization/compare_formal.py --reference 18ce45a8 --out build/ia_tile_count/formal
python test/ia_optimization/compare_interface.py --reference 18ce45a8 --out build/ia_tile_count/interface
python test/ia_tile_count/prepare_measurement.py --out build/ia_tile_count/measurement
python scripts/fpga/open_fpga_synth.py --case-config build/ia_tile_count/measurement/cases.json --cases reference current --out build/ia_tile_count/synthesis
python scripts/fpga/open_fpga_synth.py --case-config test/ia_optimization/measure.json --cases ia_production --abc9-batch-size 256 --abc9-isolate-leaves --out build/ia_tile_count/full_synthesis
```

独立时序测量给完整来源选择和取整表达式添加相同的输入、输出寄存边界，保留全部 32 位输入和最高结果进位。完整 IA 与矩阵引擎的综合结果用于检查实际模块连接中的资源数量和组合级数。
