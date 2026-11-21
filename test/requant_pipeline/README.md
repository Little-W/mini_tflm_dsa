# 量化移位流水线验证

`requant_shift_pipeline` 接收有符号 64 位乘积和 7 位移位量，输出有符号
34 位商及最近偶数舍入增量。超过 63 位的移位返回零，超出 34 位范围的商
保存饱和值。数据和移位参数在同一边沿接收，时钟使能为零时全部阶段保持。

前五个阶段依次完成 32/16、8、4、2、1 位移位选择，并逐步缩窄需要保存的
数据。后两个阶段保存限定后的商及舍入增量。模块延迟为七个使能边沿，
`vec_requant_full` 的并行配置保留十二个寄存阶段，支持每周期接收一个输入向量。
生产配置使用 `p_compute_lanes=4`，分四批处理 16 个元素，并以输入缓冲区保存完整向量。

移位选择使用可综合条件表达式，寄存器保存中间数据、移位量、溢出和符号标志。FPGA 与 ASIC 使用相同的算术结果及使能暂停规则。

## 验证方法

完整输入证明使用独立的 64 位商和余数定义，覆盖全部乘积及移位量，验证商
和舍入增量。SAT 时序归纳在连续使能边沿进行；暂停、配置刷新和执行期间
复位由完整接口逐周期比较覆盖。

```sh
python3 test/requant_pipeline/run_formal.py --out build/requant_formal
python3 test/requant_pipeline/run_formal.py --generic --out build/requant_formal_generic
python3 test/requant_pipeline/run_interface.py --out build/requant_interface --jobs 2
python3 test/requant_pipeline/run_interface.py --xilinx --out build/requant_interface_xilinx --jobs 2
python3 test/requant_rne/run.py --out build/requant_rne
```

带 `--xilinx` 的接口比较使用 Yosys 安装目录中的 Xilinx 七系列功能模型。测试从实际模块端口生成比较器，并启用缓冲区观察断言。

接口比较分别采用 32 位和 64 位总线，每种配置执行 256 个场景，覆盖
per-tensor、per-channel、WS、IS、INT8、INT16、参数突发读取、输入间断、
尾块标志、配置刷新及执行期间复位。全部公开输出逐周期比较，当前接口包含二十二个输出。
数值测试另外检查四种量化实现，共 320,000 个输出值。

## 资源比较

以下命令在相同的 16 通道、64 位总线、32 组 IA 复用及 INT16 支持参数下，
比较参考版本和当前实现。运行前应设置可用的 `pyosys` 环境。

```sh
python3 test/requant_pipeline/measure.py --out build/requant_resources
```

独立模块保留全部公开输出，包括调试与外部使用的量化参数输出。完整 SoC
综合会继续删除未被使用的输出逻辑，因此两类资源数量应分别记录。
组合路径结果按映射单元数量统计，器件时钟频率应使用完整布局布线后的延迟分析。
