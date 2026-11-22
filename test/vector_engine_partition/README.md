# 向量引擎职责划分与阶段数组验证

向量引擎由任务控制、地址准备、操作数存储及算术组装四个职责组成。公开端口、状态编码、PE 数量、存储容量及接口时钟周期保持一致。每个设计模块位于独立源文件中。

`vector_engine_control` 保存任务状态、循环计数和各运算阶段。`vector_engine_address` 生成窗口、DMA 地址及边界条件。`vector_engine_operand_store` 保存输入、权重、偏置、量化参数和累加数据。顶层 `vector_engine` 组装 PE、共享标量运算、量化结果槽位和结果写回。

本地量化的右移量保存于 `q_right[3]`，通道下标保存于 `q_index[7]`。数组下标表示实际流水阶段；每级使用对应有效位更新，暂停时保留已保存数据。七级通道下标与数值阶段同步移动。

## 阶段状态验证

`run_pipeline.py` 分别读取独立参考引擎和当前控制模块中的实际量化状态更新语句，检查完整保存状态的归纳等价关系。参数包括 `TILE=8/16`、`PE_COUNT=4/8/16` 及本地量化开启和关闭两种情况。输入涵盖全部状态编码、参数、数据、发射条件和清空条件。

四态仿真逐周期比较全部量化状态，包含 `X/Z` 控制、数据位、异步复位、阶段暂停以及检查和失败状态中的有效位清空。

```sh
python3 test/vector_engine_partition/run_pipeline.py \
  --reference-engine /absolute/path/to/reference/vector_engine.sv \
  --out build/vector_engine_pipeline
```

## 展开结构检查

`run_structure.py` 在相同参数下展开参考和当前引擎，将所有抽象存储转换为寄存器表示后比较保存位数，统一比较公开端口以及乘法器数量和位宽。此检查覆盖 8 PE 共享量化、共享存储配置和 16 PE 本地量化、私有存储配置。

```sh
python3 test/vector_engine_partition/run_structure.py \
  --reference-root /absolute/path/to/reference \
  --out build/vector_engine_structure
```

该检查统计 RTL 展开结构；LUT、存储块和器件时序由完整综合流程测量。

## 完整功能与周期比较

`test/vector_engine/run.py` 连接实际向量引擎、DMA、窗口队列、图像前端和缓存。独立整数参考覆盖深度卷积、池化、INT8/INT16 向量运算、Add、Softmax 和最近偶数舍入，并逐字节检查输出区域及其边界。总线随机等待、错误返回、参数读取和后续任务恢复参与同一测试。

增加 `--reference-engine` 后，完整参考引擎接收相同公开输入，每周期比较全部 55 个公开输出端口。原有内部断言继续检查状态资格、窗口预留、共享权重返回、结果标签和写回数据保持。

```sh
python3 test/vector_engine/run.py \
  --pes 8 --tile 16 --bus-width 64 --window-lanes 8 \
  --shared-quant --shared-storage --check-weight-write-stage \
  --rtl-assertions --stable-stimulus --jobs 1 \
  --reference-engine /absolute/path/to/reference/vector_engine.sv \
  --out build/vector_engine_shared8

python3 test/vector_engine/run.py \
  --pes 16 --tile 16 --bus-width 32 --window-lanes 4 \
  --rtl-assertions --stable-stimulus --jobs 1 \
  --reference-engine /absolute/path/to/reference/vector_engine.sv \
  --out build/vector_engine_private16
```

每个结果文件记录实际参数、比较范围、源码 SHA256、日志及执行程序 SHA256。完整功能结果包含任务数量、数值输出数量和逐周期比较数量。
## 验证结果

`validation.json` 保存各项检查的实际参数、源码 SHA256 和结果文件摘要。两个功能配置共完成 1,232 项任务、341,486 个数值输出，并在 7,191,092 个周期内比较全部 55 个公开输出端口。

| 配置或检查 | 验证范围 | 结果 |
|---|---|---|
| 8 PE，64 位总线，8 个窗口槽位 | 共享量化与共享存储，616 项任务、170,743 个数值输出、3,455,126 个比较周期 | 通过 |
| 16 PE，32 位总线，4 个窗口槽位 | 本地量化与私有存储，616 项任务、170,743 个数值输出、3,735,966 个比较周期 | 通过 |
| 量化阶段数组 | 4 组参数的完整保存状态归纳证明，262,144 次四态比较 | 通过 |
| 窗口计数、旋转和区间条件 | 11 组任意二态输入 SAT 检查，500,000 次四态比较 | 通过 |
| 8 PE 与 16 PE 展开结构 | 保存位数分别为 9,260 和 17,074，公开端口及乘法器数量、位宽保持一致 | 通过 |
| 语法与层次 | 5 组参数，包含共享和私有配置、4 PE 与 3 PE 配置 | 通过 |

接口命名、连续连接表示、包名限定和静态参数声明位置另以源码一致性检查验证；全部算术表达式、状态更新、保存容量与流水周期保持一致。保存位数按统一的 RTL 寄存器表示统计，器件上的触发器、LUT 和存储块数量由综合结果给出。
