# SoC 互连的 CPU RAM 写入

`p_cpu_ram_write_overlap=0` 时，CPU RAM 写地址接收后保存到寄存器，首拍写数据使用该寄存地址选择字节通道。CPU 的下一笔 RAM 写地址在前一笔响应完成后接收。完整 SoC 启用该配置。NPU 在途容量继续由 `WRITE_OUTSTANDING` 决定，CPU 外设访问继续使用独立地址与数据通道。

默认参数值为 1，保留地址与首拍数据在同一周期接收的行为。AXI 地址步长通过移位生成低位清除掩码，使用普通算术计算下一地址。

## 验证结果

默认模式在 8 组参数下通过完整公开输出及共同状态的逐周期等价证明，并通过 8 组容量与目的端口寄存关系的无界证明。严格四态比较覆盖 20,001 个周期和 73 个公开输出。

写入仿真覆盖 32、64 位总线，启用和关闭首拍重叠，以及 1、4 个在途事务。6 组配置合计完成 24,576 笔事务、126,958 拍写数据。测试逐拍检查 CPU 窄传输通道、NPU 整字数据、字节使能、固定与递增突发、末拍、RAM 和三个外设目标、独立地址与数据握手、随机背压、响应顺序、从设备错误响应以及复位后重新执行。所有 C++ 编译单元启用 UBSan。

64 位生产参数的独立综合结果为 631 个逻辑 LUT、225 个触发器和 2 个 DSP，寄存器之间最长组合路径为 6 级。整机资源和器件时序由相同源码的整机流程测量。

```sh
python test/soc_interconnect_writes/run.py --out build/interconnect_writes
python test/soc_interconnect_depth/run_formal.py \
  --reference-ref 6cf42463 --out build/interconnect_default_formal
python test/soc_interconnect_depth/check_four_state.py \
  --reference-ref 6cf42463 --out build/interconnect_default_four_state
```

`validation.json` 保存源码摘要、参数和各项结果。
