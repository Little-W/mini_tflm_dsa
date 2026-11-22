# 向量数据保存与输入选择

配置检查器、Softmax 和向量引擎分别保存控制状态与中间数据。状态和有效位使用异步复位；中间数据在对应状态的时钟边沿写入，复位有效期间保持。下游仅在数据对应的状态或有效位成立时读取，因此各模块的接收、提交与完成周期保持一致。

| 模块 | 同步保存的数据 |
| --- | --- |
| `vector_config_check` | 两个部分积、范围尺寸与填充值、两个坐标检查结果、范围基地址、范围字节数和范围末地址 |
| `vector_engine` | 窗口响应标签和卷积核末列 |
| `vector_softmax` | 倒数舍入的商与递增标志 |

私有权重读取地址位于对应的生成分支。普通输入的逐项写入条件位于寄存数组分支；银行存储配置直接使用实际银行的行地址和写入资格。独立观察模块检查实际写使能、写数据与随后保存的十六位数值。断言使用的标签和指数数据只在断言配置中生成。

生产配置使用八个输入银行。循环选择先根据低两位从四路候选中选取各银行数据，再由高位选择两个半组。数组索引保留未知选择值的四态传播。数据、起始银行与写入描述符使用相同的接收边沿，持续接收能力保持每拍一组数据。

## 验证范围

完整生产参数的 `vector_engine` 逐周期形式比较覆盖全部公开输出，共证明 21,768 个等价点，没有增加外部输入约束。配置为 `TILE=16`、`PE_COUNT=8`、64 位总线、八路窗口和共享权重存储。

通用输入分支直接从实际 RTL 提取池化响应、输入数据选择和全部存储项，比较完整存储状态的更新并执行时序归纳。参数包括 `TILE=4/BUS_WIDTH=32/WINDOW_LANES=4`，以及 `TILE=16` 时的 `32/4`、`64/4`、`32/8` 总线与窗口组合。两份模型使用相同初始数据，外部输入保持自由。

完整配置检查器在 `TILE=4、16、64` 下通过逐周期形式比较。完整 Softmax 覆盖乘法延迟 `0、2`、输入寄存开关以及 FPGA、通用算术分支，共八组参数。

输入循环选择通过形式比较和 65,538 组严格四态比较。局部映射包含输入保存、选择逻辑和比较用输出寄存器：名义 LUT 为 451，触发器为 259，最长寄存器间组合路径为三级。该测量用于评价输入选择结构，整机资源与路径由完整 SoC 综合报告给出。

生产数值套件通过 616 个任务和 170,743 次输出比较，其中包括 143 个 Add 任务、273 个 Softmax 任务。测试使用 16 组、128 字节的缓存行，七个共享存储银行，并启用输入银行、权重预取、权重写入阶段及 RTL 控制断言。源码与日志摘要见 `validation.json`。

## 运行

```sh
python test/vector_register_storage/run_formal.py \
  --source-root . --reference-root ../synthesis_r17_final_source \
  --profiles production --out build/vector_register_storage/production

python test/vector_register_storage/run_input_branch.py \
  --source-root . --reference-root ../synthesis_r17_final_source \
  --out build/vector_register_storage/input_branch

python test/vector_config_ranges/run.py \
  --reference ef0dc75342997721bdc4110b2841445df962018e \
  --out build/vector_register_storage/configuration

python test/vector_softmax/run_formal.py \
  --reference-rev ef0dc75342997721bdc4110b2841445df962018e \
  --out build/vector_register_storage/softmax
```
