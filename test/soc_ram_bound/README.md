# SoC RAM 地址越界预测

生产 `soc_axi_ram` 与测试存储器使用相同的组合地址计算。二次幂容量在地址容量边界处并行归约低位进位和高位地址，直接计算下一次读取是否越界。固定突发、扩展地址最高位和定宽回绕均保持原表达式的结果；其余容量继续使用完整无符号比较。所有请求队列、响应寄存器、存储器读写边沿及 AXI 时序保持原有行为。

## 验证范围

- 60 组地址宽度、数据宽度和存储容量配置通过组合形式证明，覆盖全部地址、步长、突发类型和请求选择输入。输入没有增加限制。
- 8 组配置共 32,768 个含未知态的地址辅助计算样本通过严格四态比较。
- 28 组实际 RTL 仿真通过 AXI 窄传输、背压、队列、越界响应、写入及连续传输检查。数据宽度为 32 或 64 位，容量包括 1,024 和 1,031 个字，在途数包括 1、3、4，首拍延迟包括 1、2、3、8、17 拍。

256 KiB、64 位物理存储、32 位地址、读写各 4 个在途请求的独立综合结果为 499 个逻辑 LUT、68 个分布式 RAM LUT、198 个触发器、64 个 RAMB36，寄存器之间最长组合路径为 6 级。资源和路径结果来自开源 Xilinx 7 系列映射，布局布线时序须由目标器件实现流程测量。

`validation.json` 保存源码 SHA-256、参数和验证结果。

## 重复运行

```sh
python test/soc_ram_bound/run.py --out build/soc_ram_bound
python test/soc_ram_next_addr/check_helpers_four_state.py \
  --reference 415a70a48caded2797fb6c4aaf383d2bee1bde8d \
  --out build/soc_ram_helpers_four_state
python test/conv_soc_ram/run.py --rtl-source rtl/soc/soc_axi_ram.sv \
  --jobs 1 --out build/soc_ram_protocol
python scripts/fpga/open_fpga_synth.py \
  --case-config test/soc_ram_bound/cases.json --cases soc_ram \
  --out build/soc_ram_bound_synthesis \
  --max-register-path-cells 10 --require-register-path-limit
```
