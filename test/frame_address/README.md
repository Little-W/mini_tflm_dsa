# 帧地址共享计算

`frame_address_prepare` 在接收帧命令时保存输入、权重和输出地址的操作数，依次复用一个部分积运算器计算三个三十二位地址。普通行布局、分块布局、WS、IS、INT8 和 INT16 使用相同的结果接口。所有地址运算保留模 2^32 的回绕行为。

## 运算结构

每个地址写成 `A * B + C`。`A` 和 `B` 各分为十七位无符号低段和十五位无符号高段。高段乘高段从第三十四位开始，因此地址只需三个部分积：

1. `P = A_low * B_low + C`，保存低十七位。
2. `P = A_low * B_high + (P >> 17)`。
3. `P = A_high * B_low + P`。

累加器保存三十二位，完整地址为 `{P[14:0], saved_low[16:0]}`。部分积采用普通乘法表达式，累加采用普通加法表达式；综合工具选择实现资源。

`p_pipeline_products=1` 时，乘积与累加结果分别寄存，操作号、相位和基址加数随乘积保存。九个部分积连续发射，流水线排空后置位结果有效。所有构建默认使用该配置。`p_pipeline_products=0` 可用于独立模块的直接计算配置。

| 配置 | 独立模块结果延迟 | NPU 帧准备间隔 |
|---|---:|---:|
| 默认部分积寄存 | 11 个周期 | 12 个周期 |
| 独立模块直接计算 | 10 个周期 | 不用于当前 NPU 配置 |

结果有效后，三个地址保持至 `i_result_rdy` 接收。准备阶段只接受一个上下文；后续输入变化不影响已接收的操作数。中止与复位清除控制状态，随后接收的命令重新写入数据寄存器。帧执行时的计算阵列、数据精度和存储容量由顶层参数确定。

## 帧上下文与输入缓存槽号

顶层在 `frame_command_start` 接收边沿保存当前帧的行数、列数、坐标、首末帧标记和物理输入缓存槽号。后续加载器、量化和输出配置读取同一帧的寄存结果。槽号按物理缓存容量计算，并按实际地址位宽保存。

完整 NPU 观察模块在命令接收时使用独立的三十二位公式计算预期地址，在 `frame_execute_start` 比较实际地址和准备周期；同时检查输入加载器消费的缓存槽号及活动帧参数。

## 验证方法

`run.py` 使用独立的完整三十二位地址公式检查实际 RTL。每次运行包含 36,746 个完成事务、4,286 次中止和 1,512 次运行中复位，覆盖每一个计算阶段和结果等待阶段。`--pipeline-products`、`--ready-mask-abort` 和 `--asic` 分别选择流水线、就绪输出与算术编译配置。

`run_formal.py` 对实际控制 RTL 的部分积接口使用任意符号值，在 28 个周期内比较直接计算和部分积流水线的三个结果，允许任意后续复位、中止和结果反压。另行检查三十二位累加器的截断关系、部分积拆分的整数恒等式，以及分块尺寸 1、2、4、8、16、32 的地址公式。数值测试使用实际乘法表达式。

`run_context_formal.py` 检查实际调度器和顶层帧参数的接收关系。`run_npu.py` 执行 FPGA 配置的功能、容量、输出和分块布局测试。ASIC 配置由 `test/asic_integration/run.py` 执行相同类型的完整 NPU 检查。

分块布局集合包含十二个 `33×35×51` 矩阵任务，组合 WS/IS、INT8/INT16 左操作数，以及输入分块、权重分块和两者同时分块三种布局。任务从仿真程序 `build.json` 读取 `IA_COMPACT_ENABLE`，按实际输入格式选择共享存储块；当前非紧凑配置使用两个输入存储块。`1d2f7f6a` RTL 的 FPGA 与 ASIC 仿真程序均通过十二项任务，各检查 20,196 个 INT32 累加值，任务周期合计为 123,537。观察器检查 252 帧的地址和缓存槽号，其中 WS 为 144 帧，IS 为 108 帧，INT16 左操作数为 126 帧；每帧准备时间均为十二个周期。结果和源文件校验值保存在 `test/ps_compression/input_configuration_validation.json`。

```sh
python3 test/frame_address/run.py --out build/frame_address/asic \
  --pipeline-products 1 --ready-mask-abort 1 --asic
python3 test/frame_address/run.py --out build/frame_address/fpga \
  --pipeline-products 1 --ready-mask-abort 0
python3 test/frame_address/run_formal.py --out build/frame_address/formal
python3 test/asic_integration/run.py --out build/asic_integration
python3 test/frame_address/run_npu.py --out build/frame_address/npu
```
