# Softmax 数值与累加器验证

`run.py` 将 `vector_softmax` 的 INT8 输出与 TFLM 的最近偶数舍入实现比较。
测试覆盖 16 和 32 个元素的配置、输入极值、相等输入、查表响应等待、错误响应、
任务恢复和随机输入。输出目录保存构建日志、运行日志、源码摘要及结果汇总。

```sh
python3 test/vector_softmax/run.py --out build/vector_softmax_generic --depths 16 32
python3 test/vector_softmax/run.py --xilinx --out build/vector_softmax_xilinx --depths 16 32
python3 test/vector_softmax/run_accumulator_formal.py --out build/softmax_accumulator_formal
```

`--xilinx` 通过 `XILINX_FPGA` 选择 FPGA 实现，并加载 Yosys 安装目录中的
官方 `DSP48E1` 功能模型。普通仿真使用相同接收时序的寄存加法实现。
形式验证覆盖全部二十位指数整数部分、舍入进位以及任意有效、清除和复位序列。
独立参考先形成完整的二十一位舍入结果，再按模 `2^32` 累计。

指数响应在接收边沿保存；其数据及有效标志在下一边沿参与累计。最后一个
指数响应后执行一个累加完成周期，再开始归一化。指数写入和查表请求顺序
由现有握手控制。倒数和输出缩放在接收乘积时保存舍入所需的信息。

完整引擎通过共享的两周期乘法器及生产 DMA 验证此时序，命令见
`test/vector_engine/README.md`。该测试同时运行 DW、Pool、向量操作、Add 和
Softmax，覆盖 32 位及 64 位 AXI 数据接口。

当前模块的开源资源统计可使用以下命令复现。结果报告映射后的资源数量和
组合路径单元数，器件频率使用布局布线后的延迟分析。

```sh
python3 scripts/fpga/open_fpga_synth.py --case-config test/vector_softmax/cases.json \
  --cases softmax --out build/vector_softmax_resources
```
