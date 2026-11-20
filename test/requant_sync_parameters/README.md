# 量化参数的同步读取

IS 参数缓冲分别保存原始乘数、原始移位量、运算乘数和运算移位量。原始参数采用组合读取，继续提供当前周期的公开参数输出。运算参数采用同步读取，在累加输入进入乘法器 `AREG` 的同一边沿采样。

通道模式、IS bank 编号、整张量参数及 WS 通道参数也在这个边沿保存。采样后的参数选择结果直接送到乘法器右输入；右输入的 `BREG` 关闭。乘法器的输入采样、部分积和完整乘积仍占用三个使能边沿，完整量化仍包含十二个寄存阶段。`init_cfg` 暂停所有相关阶段，同地址同周期读写使用写入前的参数。

`registered_multiplier_s32` 和 `registered_multiplier_dsp` 使用 `p_b_input_register` 独立选择右输入寄存。默认值继承 `p_input_register`，现有实例继续同时选择左右输入寄存。

## 存储容量

生产配置采用 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`。IS 参数包含两个 bank，每个 bank 有 256 个位置，每个位置保存 103 位参数。全部 IS 参数共 52,736 位；WS 参数共 1,648 位。

完整生产 NPU 的缓冲数组和 WS 参数数组位数保持一致。同步阶段增加 120 位状态，由两个 bank 的 78 位同步读结果、39 位整张量参数、两个模式位和一个 bank 编号位组成。

## 综合结果

完整 `vec_requant` 的全部公开输出参与综合，参考提交为 `a939a412`，目标器件为 `xc7a200tfbg484-3`，使用 Yosys、ABC9 和 Xilinx 7 系列原语。

| 指标 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 7,687 | 7,609 |
| 分布式 RAM LUT | 1,120 | 800 |
| SRL LUT | 192 | 160 |
| 名义 LUT 位置合计 | 8,999 | 8,569 |
| 触发器 | 6,469 | 7,213 |
| RAMB18E1 | 0 | 2 |
| DSP48E1 | 96 | 96 |
| 最长寄存器间组合单元数 | 15 | 15 |

名义 LUT 位置减少 430 个。上述 LUT 数量为布局前的统计；物理 LUT 位置及 150 MHz 时序由完整 SoC 的器件实现统计。

## 功能验证

`run_parameter_formal.py` 对实际展开的参数存储进行字段比较。各字段的存储深度、位宽、初始化参数、读写行为参数完全相同；对应读数据作为每周期任意输入，形式比较检查全部存储驱动端口、控制输出、公开原始参数及实际乘法和移位采样结果。因此，相同的对应存储字段持续接收相同的读写操作，并产生相同的参数采样结果。生产配置覆盖全部 52,736 位 IS 参数和 1,136 位采样参数，5,079 个比较位全部通过。输入配置、DMA 响应和暂停均不受约束。

`run_multiplier_formal.py` 分别检查通用 RTL 和官方 `DSP48E1` 模型，将上游参数寄存与独立的乘法器输入寄存配合。输入采样先通过形式比较，再以已经证明相同的操作数检查完整 INT32 乘法。通用实现比较 64 位输入和 338 位算术结果；DSP 实现比较 192 位输入和 338 位算术结果。四项证明全部通过。原有乘法器的六项默认参数证明也全部通过。

完整 FPGA 分支使用官方 `LUT6_2` 和 `DSP48E1` 模型逐周期比较所有公开端口，覆盖 DMA 命令与响应、原始参数、INT8/INT16 数值、有效信号、任务结束和暂停。

| 总线宽度 | 场景 | 周期 | 输出向量 | DMA 命令 | DMA 返回拍 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 32 | 256 | 528,662 | 206,800 | 922 | 12,322 |
| 64 | 256 | 528,662 | 209,001 | 958 | 6,496 |

两种总线配置均通过。`run_capacity.py` 展开完整生产 NPU，检查所有缓冲数组容量以及新增阶段状态。`measurement.json` 保存源码、参考实现、原语模型、综合网表和验证记录的 SHA-256，以及实际连接的最长组合路径。

## 运行命令

以下命令在仓库根目录执行，`PYTHONPATH` 指向安装了 Yosys Python 接口的环境，`VERILATOR_BIN` 指向 Verilator 可执行程序。

```sh
python3 test/requant_sync_parameters/run_parameter_formal.py \
  --out build/requant_sync_parameters/parameter_formal \
  --bus 64 --lanes 16 --reuse 32

python3 test/requant_sync_parameters/run_multiplier_formal.py \
  --out build/requant_sync_parameters/multiplier_formal

python3 test/requant_product/run_formal.py \
  --out build/requant_sync_parameters/default_multiplier_formal

python3 test/requant_pipeline/run_interface.py \
  --reference-rev a939a412 --xilinx --bus-width 32 64 \
  --verilator "$VERILATOR_BIN" --jobs 2 \
  --out build/requant_sync_parameters/interface

python3 test/requant_sync_parameters/run_capacity.py \
  --out build/requant_sync_parameters/capacity \
  --verilator "$VERILATOR_BIN"

python3 test/requant_sync_parameters/prepare_measurement.py \
  --out build/requant_sync_parameters/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_sync_parameters/inputs/cases.json \
  --cases reference candidate \
  --out build/requant_sync_parameters/synthesis \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_synthesis.lock
```
