# 向量位置、串行读取与准备寄存器检查

本目录检查 `vector_engine.sv` 的位置递增、串行读取选择，以及提前保存的数据在实际消费周期是否正确。组合关系使用实际源码提取后的形式证明；通道组结束条件在完整状态机上进行归纳证明，各项准备值同时由绑定到真实向量引擎的观察模块在数值回归中检查。

## 组合关系

`run_formal.py` 从指定提交和当前 `vector_engine.sv` 提取位置递增、串行读取地址和串行读取数据表达式。证明覆盖全部 32 位位置，包括 `0xffff_ffff` 递增后的回绕。累加存储中的每个数据值、状态编码和索引输入均不施加假设。

串行读取地址在全部状态下比较。数据比较在数组索引有效时启用，无效索引时双方比较输出统一为零。`TILE=1、3、4、8、16、32、64` 的七组证明均检查对应参数展开后的实际表达式。

```bash
python test/vector_control_datapath/run_formal.py \
  --reference dde5e7c9 --out build/vector_control_datapath/formal
python test/vector_dma_address/run_formal.py \
  --reference-rev dde5e7c9 --out build/vector_control_datapath/dma
```

第二个入口同时检查参数行描述符准备、读取配置、读取地址、写回起点和四组 DMA 范围，详细说明见 [向量 DMA 地址与参数准备](../vector_dma_address/README.md)。两个入口均记录实际源码、辅助模块、证明脚本和日志的 SHA256。

## 卷积核位置与输入槽状态

卷积核位置的递增值通过三位分组前缀加法计算。扩展到 32 位的末项比较与原计数宽度的模加法比较分别生成，两种比较各自保持原有溢出行为。`run_tap_formal.py` 直接提取三个实际实例，对宽度 1、2、6、8、9、11、16、31、32 检查全部输入组合。

每个输入槽独立保存就绪状态。返回末拍设置该槽状态，计算消费和初始化清除对应状态；同拍发生时清除具有最高优先级。`run_ready_formal.py` 先证明真实状态机中的通道组结束条件，再使用该恒等式比较四组 TILE、PE 数量和共享资源配置的输入槽更新逻辑。展开后的真实 `input_ready` 寄存器及其更新逻辑完整保留，其余控制状态作为任意输入。`dw_issue_fire` 的实际状态译码和就绪反馈保留在检查中，不添加输入假设。

`run_group_formal.py` 直接展开生产向量引擎，保留实际状态机、通道计数和全部相关状态更新。证明目标为：每个 `EXECUTE_COMMIT` 周期，`compute_group_last_q` 等于 `compute_index + PE_COUNT >= active`。归纳证明仅要求首周期复位，不替换内部状态、不限制请求数据或后续输入。共享存储和共享量化配置分别检查。

```bash
python test/vector_control_datapath/run_tap_formal.py \
  --out build/vector_control_datapath/tap
python test/vector_control_datapath/run_ready_formal.py \
  --reference dde5e7c9 --out build/vector_control_datapath/ready
python test/vector_control_datapath/run_group_formal.py \
  --out build/vector_control_datapath/group
python test/vector_window_count/run_formal.py \
  --reference dde5e7c9 --out build/vector_control_datapath/window_count
python test/vector_coordinate_bounds/run_formal.py \
  --reference-rev dde5e7c9 --out build/vector_control_datapath/coordinate_bounds
```

窗口计数检查覆盖 1、3、4、8、16、31、32 个通道以及完整 32 位累计值。坐标检查覆盖当前位置、下一列和下一行的全部 34 位坐标输入及 16 位图像尺寸。各项摘要记录实际引擎和公共依赖的 SHA256。

## 实际消费周期

`test/monitors/vector_engine_observer.sv` 中的 `vector_control_datapath_observer` 直接访问真实引擎状态、准备寄存器、请求地址和累加存储。观察模块通过 `bind` 接入仿真，不参与生产状态更新。

| 检查对象 | 保存或准备周期 | 消费周期与断言 |
| --- | --- | --- |
| 参数行步长和连续行资格 | `CHECK` | 保存原始配置表达式；之后检查寄存器与保存值相等，并在参数 `LOAD_REQ/LOAD_WAIT` 中检查其仍等于当前配置表达式 |
| Softmax 查询索引 | `SOFT_RUN` 接收查询请求 | `SOFT_LUT_REQ/SOFT_LUT_WAIT` 中检查保存索引、查询模块当前索引和实际 DMA 地址一致 |
| 下一窗口有效条件 | `EXECUTE` | `EXECUTE_COMMIT` 中检查前一状态为 `EXECUTE`，保存条件等于此前条件和当前消费条件 |
| 通道组结束条件 | `EXECUTE` | `EXECUTE_COMMIT` 中检查寄存值等于当前通道索引与有效通道数的直接比较 |
| 归约操作数 | `VECTOR_NEXT` 读取第零项，`VECTOR_REDUCE` 提前读取下一项 | 每个 `VECTOR_REDUCE` 周期检查操作数等于 `acc_buf[reduce_index]`，入口索引为零，后续索引逐次递增 |
| 归约期间累加存储稳定性 | 进入归约及每个归约周期 | 检查所有累加存储项的实际写使能均为零 |

这些断言检查真实执行序列，无外加输入假设。观察模块在仿真正常结束时输出 `VECTOR_CONTROL_DATAPATH_PASS`，分别记录参数、查询、窗口提交和归约的消费周期数。数值回归同时使用独立整数参考模型检查最终输出，并执行随机 AXI 等待、错误恢复、Add 和 Softmax 场景。

```bash
python test/vector_engine/run.py \
  --pes 8 --tile 16 --bus-width 64 --window-lanes 8 \
  --cache-sets 128 --cache-policy 3 --cache-line-bytes 16 \
  --shared-storage --xilinx --jobs 1 \
  --out build/vector_control_datapath/shared_storage
python test/vector_engine/run.py \
  --pes 16 --tile 16 --bus-width 64 --window-lanes 8 \
  --cache-sets 128 --cache-policy 3 --cache-line-bytes 16 \
  --shared-quant --xilinx --jobs 1 \
  --out build/vector_control_datapath/shared_quant
python test/vector_control_datapath/collect_report.py \
  --control build/vector_control_datapath/formal \
  --dma build/vector_control_datapath/dma \
  --storage build/vector_control_datapath/shared_storage \
  --quant build/vector_control_datapath/shared_quant \
  --proof window_count=build/vector_control_datapath/window_count/summary.json \
  --proof coordinate_bounds=build/vector_control_datapath/coordinate_bounds/summary.json \
  --proof tap=build/vector_control_datapath/tap/summary.json \
  --proof input_ready=build/vector_control_datapath/ready/summary.json \
  --out build/vector_control_datapath/verification.json
```

数值测试与汇总脚本均支持 `--source-root`，可指定同一个固定 RTL 目录。汇总脚本要求组合证明和两个数值配置全部成功，四类消费周期均有覆盖，原有 `pipeline_dw_c16` 场景包含请求和响应同时传输。它还检查两组数值测试的全部编译 RTL 文件集合与 SHA256 一致，并与固定源码、组合证明和附加证明的源码逐项比较。只有满足这些条件才生成通过结果。形式证明覆盖上述组合表达式的全部二值输入；跨周期关系的执行覆盖由数值回归摘要单独记录。

## 当前数值结果

两种配置使用相同的 35 份 RTL，均已通过。引擎 SHA256 为 `a12419b9777f0420b381fa4c696309276782a5b39c96d980bd638b766c5d3a8a`。

| 配置 | 通用场景 / 输出 | Add 场景 / 输出 | Softmax 场景 / 输出 | 输出总数 |
| --- | ---: | ---: | ---: | ---: |
| PE8 共享存储 | 615 / 170745 | 143 / 135508 | 273 / 2188 | 308441 |
| PE16 共享量化 | 615 / 170811 | 143 / 135749 | 273 / 2188 | 308748 |

两组共 2,062 个场景、617,189 个输出元素。PE8 的参数、查询、提交和归约检查分别覆盖 5101、43983、7485、720 个周期；PE16 分别覆盖 5025、43869、5244、720 个周期。详细配置、消费者周期检查、源码散列及形式证明见 [verification.json](verification.json)。
