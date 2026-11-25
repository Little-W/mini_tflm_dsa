# DMA 通道零点加法验证

`axi_linear_block_dma` 将每个输入通道转换为十六位数值，再计算完整的模加结果。组合结果的 `use_dsp="simd"` 属性允许综合工具把独立通道加法分配到原生算术单元。格式选择、加法位宽、返回资格和寄存时序均由原有 RTL 表达式定义。

验证分为三个部分：

1. 完整 DMA 的时序等价检查覆盖 11 组参数，包括生产配置、非二次幂描述符数量、不同数据与地址宽度以及较短突发长度。全部输入均保持自由。
2. `check_mapped.py` 比较修改前后的完整可执行 RTL 词法内容，并从实际生产配置综合网表提取 128 位通道加法及对应零点寄存器。验证使用完整器件功能模型，包含综合工具吸收到 DSP 中的输入寄存器。
3. 生产配置事务测试检查固定事务和随机停顿下的描述符顺序、标签、页边界、错误归属和输出数据。

复现命令如下，运行环境需要提供 Pyosys、Verilator 和 C++20 编译器：

```sh
mkdir -p build/dma_unpack_simd
git show f3e85795:rtl/npu/dma/axi_linear_block_dma.sv > build/dma_unpack_simd/reference.sv
python test/dma_byte_layout/run_formal.py --fpga --production-parameters --context-parameters --address-parameters --reference-rtl build/dma_unpack_simd/reference.sv --out build/dma_unpack_simd/formal
python scripts/fpga/open_fpga_synth.py --case-config test/dma_unpack_simd/measure.json --cases linear_dma --out build/dma_unpack_simd/synthesis
python test/dma_unpack_simd/check_mapped.py --reference-rtl build/dma_unpack_simd/reference.sv --mapped-source rtl/npu/dma/axi_linear_block_dma.sv --mapped-json build/dma_unpack_simd/synthesis/linear_dma/mapped.json --out build/dma_unpack_simd/mapped_check
python test/linear_dma_context/run.py --size 64 --cache-blocks 64 --outstanding 4 --contexts 4 --bus-width 64 --dma-max-bytes 2048 --fpga --out build/dma_unpack_simd/context
```

生产参数的同一开源综合流程测得逻辑 LUT 为 1,493 个，相比修改前减少 64 个；触发器为 784 个，分布式存储占用 60 个 LUT，RAMB18 为 1 个，DSP 为 5 个。寄存器之间最长组合路径为 10 级。这里记录综合后的逻辑单元数量和连接级数，布局布线后的占用与时序由器件实现流程测量。
