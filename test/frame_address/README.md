# 帧地址共享计算

`frame_address_prepare` 在接收帧命令时保存 IA、权重和输出地址的操作数，使用一个 `DSP48E1` 依次计算三个完整的三十二位地址。普通行布局、分块布局、WS、IS、INT8 和 INT16 使用相同的结果接口。所有地址运算保持模 \(2^{32}\) 的回绕行为。

## 运算与周期

每个地址写成 `A * B + C`。`A` 和 `B` 分成十七位无符号低段和十五位有符号高段：

\[
A\equiv A_l+2^{17}A_h\pmod {2^{32}},\qquad
B\equiv B_l+2^{17}B_h\pmod {2^{32}}.
\]

在模 \(2^{32}\) 的地址空间中，三个乘积 `A_l * B_l`、`A_l * B_h` 和 `A_h * B_l` 保留全部有效位。基址与剩余偏移组成 `C`。DSP 的 `PREG` 保存每次乘加结果，运算依次为：

1. `P = A_l * B_l + C`。
2. 保存 `P[16:0]`，计算 `P = A_l * B_h + (P >>> 17)`。
3. 计算 `P = A_h * B_l + P`。

完整地址由 `{P[14:0], saved_low[16:0]}` 组成。DSP 使用 `AREG=0`、`BREG=0`、`MREG=0`、`PREG=1`，每个乘加边沿均经过输出寄存器。

| 相对接收边沿 | 操作 |
| --- | --- |
| 0 | 保存三个地址的操作数 |
| 1–3 | 计算 IA 地址 |
| 4 | 保存 IA 地址，开始权重地址计算 |
| 5–6 | 完成权重地址计算 |
| 7 | 保存权重地址，开始输出地址计算 |
| 8–9 | 完成输出地址计算 |
| 10 | 保存输出地址，置位结果有效 |
| 11 | NPU 接收三个地址并启动当前帧 |

独立单元的结果延迟为十个周期，结果保持至接收。NPU 中的帧控制器相对 `frame_command_start` 增加十一个准备周期；帧执行期间的阵列尺寸、向量 PE 数、量化精度和存储容量保持一致。任务总周期由实际调度和 DMA 等待共同决定，测试记录每项任务的周期。

准备状态只接收一个上下文。计算期间再次出现的输入请求不会覆盖当前操作数；接收后的输入变化不会改变当前结果。中止与复位清除控制状态，数据寄存器由随后接收的上下文重新写入。NPU 在准备完成后启用帧完成统计和权重预取。

## 独立综合

生产地址宽度为三十二位、分块尺寸为十六。下表比较原三个地址表达式和完整共享准备单元；原表达式的输入、输出均为组合端口。

| 指标 | 三个地址表达式 | 共享准备单元 |
| --- | ---: | ---: |
| 逻辑 LUT | 392 | 433 |
| DSP48E1 | 15 | 1 |
| 触发器 | 0 | 505 |
| 分布式 RAM、SRL、块 RAM | 0 | 0 |
| 最长内部寄存器间组合路径 | 无内部寄存器 | 11 |

完整 SoC 的面积由全局算术分配和合法布局统计。该单元释放十四个 DSP；其实际整机 LUT 变化由完整 SoC 测量结果给出。150 MHz 使用目标器件的完整布局布线时序报告确认。

## 验证

`run_formal.py` 使用官方 `DSP48E1` 模型比较通用实现和 FPGA 实现的全部状态及公开输出，共证明 881 位。输入、结果接收和中止均保持任意。另以 130 个任意部分积与加数输入位证明三次乘加的完整地址结果，并验证乘积拆分的整数恒等式。对分块尺寸 1、2、4、8、16、32，各证明 130 个任意输入位下的地址位段组合与回绕关系。

`run.py` 同时检查完整三十二位独立地址参考、通用实现和官方原语实现。检查包含 36,746 个完整事务、4,286 次中止、1,512 次运行中复位及 185,328 个结果等待周期，共运行 672,662 周期。实际综合网表使用相同场景完成数值和周期检查。

`--ready-mask-abort` 选择受测的 `p_ready_mask_abort`，默认值为1；设为0时直接检查生产实例的内部空闲就绪输出。测试逐个覆盖十个计算阶段及结果等待阶段的中止与复位，并检查中止与开始同时有效的优先级。`test/npu_admission/run_numeric.py` 依次运行参数0和1，保存各组统计与对应源码哈希。

`run_npu.py` 使用生产配置和官方原语执行完整 NPU 功能、容量、错误恢复及输出测试，并增加十二项 WS/IS、INT8/INT16、LHS/RHS 分块布局任务。附加观察器在每个帧接收边沿保存原地址公式的结果，在执行边沿检查三个地址和十一个周期的准备间隔。

完整 NPU 测试通过 86 项任务和 216,348 个 INT32 输出检查。1,860 个帧命令全部在接收后的第十一个周期启动，共包含 927 个 WS 帧和 933 个 IS 帧；其中 252 个帧使用分块布局，186 个帧使用十六位输入。

| 测试组 | 任务数 | INT32 检查数 | 帧命令数 | 原任务总周期 | 共享地址计算后的总周期 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 功能与错误恢复 | 38 | 11,118 | 0 | 137,819 | 137,819 |
| 容量 | 21 | 173,642 | 1,578 | 585,078 | 600,816 |
| 输出 | 15 | 11,392 | 30 | 41,813 | 41,928 |
| 分块布局 | 12 | 20,196 | 252 | 100,839 | 102,051 |

每项任务的读取请求数、读取和写入字节数、输出数量、PS 记录数量与帧数量均与参考运行一致。功能测试的全部逐项统计相同。帧任务的准备阶段可以与已有的 DMA 活动重叠，表中记录实际任务总周期。

生产结构检查确认保留 458,752 位 IA/PS 共享数据存储、九个共享存储声明、256 个阵列单元和八个向量 PE。源码哈希、形式证明、数值检查、逐项周期比较及综合结果保存在 [measurement.json](measurement.json)。

## 复现

以下命令在仓库根目录执行，`PYTHONPATH` 指向含 `pyosys` 的工具环境。

```sh
python3 test/frame_address/run_formal.py --out build/frame_address/formal
python3 test/frame_address/run.py --out build/frame_address/numeric --verilator verilator --jobs 1
python3 test/frame_address/prepare_measurement.py --out build/frame_address/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config build/frame_address/inputs/cases.json --cases reference candidate --out build/frame_address/synthesis --lock-file /tmp/mini_tflm_dsa_synthesis.lock
python3 test/frame_address/check_structure.py --mapped build/frame_address/synthesis/candidate/mapped.json --out build/frame_address/structure.json
python3 test/frame_address/run.py --out build/frame_address/numeric_mapped --verilator verilator --jobs 1 --mapped build/frame_address/synthesis/candidate/mapped.v
python3 test/frame_address/run_npu.py --out build/frame_address/npu --verilator verilator --jobs 1 --build-timeout 7200
```
