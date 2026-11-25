# 操作数存储等价检查

`run_formal.py` 展开 `vector_engine_operand_store` 及其存储依赖，比较全部匹配状态和输出。四组参数覆盖生产配置、私有权重存储、8 个元素的分块，以及 16 通道共享量化。存储容量采用模块的完整参数值。

```sh
python test/vector_operand_store/run_formal.py --out build/vector_operand_formal
```

`run_four_state.py` 使用同一组输入逐周期比较全部 29 个公开输出。输入包含并发写入、任意控制组合以及数据和选择信号中的 `X`、`Z`，并检查已知非零输入和权重的覆盖数量。每次默认运行 20,003 个周期，输出源码哈希、编译命令和结果摘要。

```sh
python test/vector_operand_store/run_four_state.py --out build/vector_operand_four_state
python test/vector_operand_store/run_four_state.py --out build/vector_operand_private --bus-width 32 --window-lanes 4 --shared-storage 0
python test/vector_operand_store/run_four_state.py --out build/vector_operand_tile8 --tile 8 --pes 4
python test/vector_operand_store/run_four_state.py --out build/vector_operand_quant --pes 16 --window-lanes 16 --shared-quant 1
```

参考操作数实现由 `--reference` 指定，默认提交为 `5adaa4c9`，待测实现取当前源码。形式检查需要提供 `read_slang` 的 Pyosys，四态检查使用 Icarus Verilog 12。

非银行输入存储配置的仿真副本将常量数组项改用组合过程赋值，参考与待测副本使用相同转换；原始文件和副本的哈希均写入摘要。生产配置直接编译 RTL 源文件。
