# 部分和读取与共享存储错误控制

`ps_frame_read_enable` 将首行状态、后续行状态、帧请求、帧接受和容量状态在同一个组合模块内归并。读取请求在原周期发出，读取地址、返回寄存器及解码缓冲更新保持一致。

`shared_ram_capacity_next` 提前计算已有错误、配置合法性及其他访问错误。每两个部分和通道独立检查读取请求，再与已准备的错误状态汇总。四个读取通道仍分别检查许可、地址范围和同地址读写冲突。复位、配置切换、暂停、错误保存和恢复均保留逐周期行为。

两个实现均采用普通 RTL。输入包含未知值时，父模块通过条件更新表达式传播四态结果。

## 完整模块测量

参照提交为 `d4aabbb43147e0ef159439b20d1bee515535f49a`。采用相同依赖文件和 `physical-cost` 映射：最大 LUT 输入数 8、较小 LUT 面积权重 1、连线延迟参数 300 ps、延迟目标 6,667 ps。

| 模块与指标 | 参照实现 | 当前实现 |
|---|---:|---:|
| 完整 PS 帧存储名义 LUT | 964 | 964 |
| PS 最长寄存器路径 | 10 | 10 |
| `frame_accept` 到 `ram_read_en` | 2 | 1 |
| `frame_request` 到 `ram_read_en` | 2 | 1 |
| 完整共享通道名义 LUT | 1,158 | 1,162 |
| 共享通道最长寄存器路径 | 8 | 9 |
| `i_ps_read_en` 到 `o_capacity_fault` | 4 | 2 |
| `i_access_enable` 到 `o_capacity_fault` | 2 | 2 |

PS 生产配置使用 256 行上限、16 个帧目录、49,152 字节存储池、8,192 字节物理块及外部固定部分和通道。FF 为 836，DSP48E1 为 3，RAMB18E1 为 15，均保持不变。

共享通道生产配置使用七个 8,192 字节物理块，启用成对 IA 端口、非空写掩码资格、共享写数据寄存以及允许更新非有效返回数据的已有选项。FF 为 10，RAMB36E1 为 34，均保持不变。完整通道的 9 级路径起于已保存的存储分配状态，终止于容量错误寄存器。

路径报告在端口位置增加仅供图分析使用的寄存器端点，统计实际网表中的组合单元；该步骤不改变被综合的 RTL。完整路径、资源和源码校验值见 `measurement.json`，整机连接后的结果由 SoC 综合报告记录。

## 验证范围

- PS 帧存储在五种参数配置、两种显式编译模式下完成 10 项完整模块等价证明，共 201,594 个等价位。外部输入及握手未添加取值限制，全部公开输出、共同状态和实际内部存储内容均参与比较。
- PS 帧存储完成 81,920 个四态周期，比较每个周期的全部公开输出，包含配置切换、请求取消、命令接受、写入、回放和未知值输入。
- 共享存储在五种参数配置、两种编译模式下完成 10 项时序归纳检查。首次采样复位后，全部外部输入及复位自由变化。所有物理读写命令的使能、地址、数据和掩码逐位比较，独立任意返回数据下的配置、选择状态和公开返回值逐周期相等。
- 共享存储真实数组完成 81,920 个四态周期。每个时钟周期比较全部实际数组内容，覆盖六、七、八、九个物理块，包含同时独立访问、非法请求、暂停、复位、配置切换以及返回数据保持。
- 实际共享 RAM 的 INT32 写入、读取和回放在通用及 FPGA 模式下完成 59,468 个周期、1,326 个命令及 471,392 次数据检查。每周期比较完整 PS 帧存储的所有公开输出。
- 当前设计的 337 个模块和 5,911 个端口通过中文说明及端口功能注释检查。

完整结果及文件校验值保存在 `validation.json`。

## 运行方法

```sh
python3 test/ps_shared_read_control/run_ps_formal.py --out build/ps_shared_read_control/ps_formal
python3 test/ps_shared_read_control/run_shared.py --out build/ps_shared_read_control/shared_check
python3 test/ps_capacity_shared/run_four_state.py --reference d4aabbb43147e0ef159439b20d1bee515535f49a --out build/ps_shared_read_control/ps_four_state
python3 test/ps_shared_read_control/run_numeric.py --out build/ps_shared_read_control/numeric
python3 test/ps_shared_read_control/measure.py --out build/ps_shared_read_control/measurement
```
