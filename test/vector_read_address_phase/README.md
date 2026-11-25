# 向量读取资格与地址运算

控制模块在保存状态的同一时钟沿保存 Softmax 表读取和池化读取资格，在更新读取类型时同时保存六种普通读取来源的独热选择。地址模块直接使用这些寄存输出选择基地址、偏移和通道号。状态转移、读取类型更新条件和请求发出的周期保持一致。

完整地址为两个 32 位无符号分量和一个 16 位无符号通道号之和，结果保留 34 位。三个分量先压缩为两项，随后分别计算低 18 位和高 16 位的部分和。普通加法表达式上的 `use_dsp="simd"` 属性允许综合工具自动推断并行运算；低段进位通过逐位传播条件加入高段。全部运算保持组合行为。

四态仿真使用相同的三位分组规则传播未知值。独立地址模块默认从状态和读取类型生成选择条件，向量引擎启用已经保存的读取资格。

## 权重读取资格

`state_weight_zero_address` 表示 `OUTPUT_INIT` 或 `DW_FINISH`，与完整状态字在同一个时钟沿保存。权重读取地址使用该资格选择零地址或已保存的预取地址。核位置、末项标志及预取寄存器保持各自的更新条件。

状态保持、异常转移、复位和非法状态处理共同维护全部状态资格。下面的控制字证明同时检查已有字段及新增读取字段，完整向量比较覆盖读取等待、预取、任务切换、写入阶段和错误恢复。

## 复现

```sh
python test/vector_read_address_phase/check_registered_sources.py \
  --out build/vector_read_sources
python test/vector_read_address_phase/check_arithmetic.py \
  --out build/vector_read_arithmetic
python test/vector_dma_address/run_formal.py \
  --out build/vector_address_equivalence
```

`check_registered_sources.py` 读取生产源码中的全部 89 处状态更新和 9 处读取类型更新，检查已有字段、右侧表达式和更新位置。七项形式检查覆盖控制字、保持关系、复位和归纳步骤。四态比较遍历六位状态与三位读取类型的全部 `0/1/X/Z` 编码，共 262,144 组。

`check_arithmetic.py` 对完整 34 位结果执行 200,000 次四态比较，包含两种分组保持参数。随后进行原生 Xilinx 7 系列映射，展开完整器件功能模型，对所有地址位及进位执行无限时序等价检查。测试中的数学参考直接计算两个完整基地址和通道号的无符号和。

`run_formal.py` 比较完整地址子模块，包括 DMA 配置、范围、行列数、突发长度、坐标边界及内部寄存行为。五组参数分别覆盖生产配置、32/128 位总线和 3/32 个通道。新增资格输入按已证明的控制字关系连接，其余输入保持任意取值。

完整向量逐周期比较入口为 `test/vector_engine/run.py --reference-engine ...`，参考文件可由 `test/vector_engine/prepare_revision_reference.py` 从指定提交独立导出。生产配置使用 16 个通道、8 个计算单元、64 位总线、8 个窗口通道和 7 个 8192 字节共享存储体。
