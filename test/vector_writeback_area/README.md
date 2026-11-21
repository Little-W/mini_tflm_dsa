# 向量写回数据选择验证

`vector_writeback` 提供通用合并和字节合并两种配置。通用配置保留任意有效字节数的连续请求合并。设置 `p_coalesce_bytes_only=1` 时，完整数据字使用独立事务，连续字节结果可以合并。`vector_engine` 使用字节合并配置，其 DW 请求采用 INT8 输出，其他操作发出独立写入请求。生产调用方提交的请求长度为 `1` 至 `4*TILE` 字节。

字节合并配置在 `TILE` 为二次幂时旋转 `TILE` 个字节，并将结果分配到待写队列。若目的位置为 `e`，追加偏移为 `p`，被写入的字节满足 `e>=p`，应选择输入字节 `e-p`。循环移位首先选择 `(e-p) mod TILE`，再以 `e<p+TILE` 区分有效输入与零填充。完整数据字在队列为空时接收，因此直接使用各字节的固定位置。其他 `TILE` 配置采用通用移位电路。

每次接收请求时保存 `request_address + request_bytes`，后续追加请求直接与已保存的连续末地址比较。该地址与待写字节数在同一时钟边沿更新，写入队列的接收和发送周期保持一致。

## 逐周期比较

```bash
python3 test/vector_writeback_area/run.py --verilator /path/to/verilator --jobs 2
```

程序从指定 Git 提交读取参考 RTL，比较当前实现和参考实现的请求接收、写事务参数、输出字节使能、完整有效输出数据、完成状态和错误状态。字节合并配置使用与向量引擎相同的请求条件：只有 INT8 请求允许合并。

测试执行 11 组配置，每组 30,000 个周期，包括 `TILE=1/3/15/16/32`、32/64/128 位总线、两种合并配置、随机停顿、错误响应、强制发送、连续与不连续地址、处理中复位，以及字节请求中的零填充。测试结果及源文件 SHA-256 保存在 `build/vector_writeback_equivalence/summary.json`。

## 写入内容检查

```bash
python3 test/vector_writeback/run.py --verilator /path/to/verilator --jobs 2
```

该测试使用独立模拟内存检查接收的每个字节恰好写入一次，并检查随机等待期间写数据保持不变。32 位和 64 位总线分别执行两种合并配置；每组包含 256 次请求。

面积比较应对同一器件、相同参数和工具设置分别执行综合。独立模块的资源数量用于评估该模块的实现选择，完整 SoC 的资源与 150 MHz 时序由完整设计的布局布线结果确定。

## 特殊输入与事务等待

```bash
python3 test/vector_writeback_area/run_corners.py --verilator /path/to/verilator --jobs 2
```

两种合并配置分别执行 30,000 个周期。在复位释放后将请求起点设为 `0xfffffff8`，检查跨越 32 位地址空间末端的请求；零长度刺激用于参考实现与当前实现的逐周期一致性及复位恢复检查。测试统计实际发生的地址进位、零长度请求、授权等待、数据等待、错误响应和强制发送事件，要求每项均被执行。

## 同条件综合结果

```bash
python3 test/vector_writeback_area/measure.py --out build/vector_writeback_measurement
```

脚本使用 Yosys 的 `synth_xilinx`、xc7 器件族、`TILE=16` 和 64 位总线，自动读取参考提交与当前文件。当前配置与 `vector_engine` 中的字节合并配置相同。参考提交为 `4dee27ffec4dc891daf2681379f8b3fd27fd41f2`。详细测量记录见 [measurement.json](measurement.json)。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| LUT 单元 | 3,806 | 1,679 |
| 触发器 | 1,153 | 1,186 |
| BRAM / DSP | 0 / 0 | 0 / 0 |
| 最长寄存器间组合路径单元数 | 15 | 8 |
| 包含模块输入的最长组合路径单元数 | 15 | 10 |

当前实现减少 2,127 个 LUT 单元，增加 33 个用于保存连续末地址的触发器。组合深度按综合后已连接的 LUT、进位和选择单元统计。完整 SoC 的面积和 150 MHz 时序采用完整设计的布局布线报告。
