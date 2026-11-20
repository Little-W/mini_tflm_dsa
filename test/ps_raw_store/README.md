# INT32 部分和帧存储验证

`run.py` 使用独立内存模型检查帧分配、逐行写入、回放、容量压力、配置更新和错误恢复。
`--reference` 同时实例化指定提交的实现，逐周期比较所有公共输出。

```sh
python3 test/ps_raw_store/run.py --out build/ps_store_regular \
  --reference b8b34d5 --verilator verilator-modern --jobs 2
python3 test/ps_raw_store/run.py --out build/ps_store_large \
  --reference b8b34d5 --large --verilator verilator-modern --jobs 2
```

常规检查覆盖 818 个命令、89,648 个 INT32 数值和 18,501 个周期。
大容量检查覆盖 15 个命令、30,720 个 INT32 数值和 3,990 个周期，包括 256 行帧与存储边界。
两组检查均通过数值和逐周期比较。

## 容量判断

每行包含四个 128 位存储字，帧起始位置按整行分配。`ps_frame_store_capacity`
将可用存储字转换为完整行数，减去起始行号，分别比较实际行数和预留行数。
输入行数的高位与减法借位单独检查，因此完整 32 位输入均保留确定的容量判断。
该模块为组合逻辑，帧请求、接受、写入和回放周期保持不变。

```sh
python3 test/ps_raw_store/run_capacity_formal.py --out build/ps_capacity_formal
python3 test/ps_raw_store/measure_capacity.py --out build/ps_capacity_synth \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock
```

形式验证覆盖 12 组位宽配置，直接对比生产模块与完整 64 位参考表达式。
每组检查全部输入组合，包括 32 位实际行数、32 位预留行数、零容量、起始位置越界、
不足一整行的剩余存储字，以及采用宽参数运算的配置。

生产配置为 16 帧、每帧最多 512 行、49,152 字节存储池和 8,192 字节存储块。
Yosys 0.71、ABC9、Xilinx 7 系列映射结果如下。参考源码为 `b8b34d5`。

| 测量范围 | 参考逻辑 LUT | 当前逻辑 LUT | 参考组合级数 | 当前组合级数 |
| --- | ---: | ---: | ---: | ---: |
| 带输入输出寄存器的容量判断 | 67 | 43 | 15 | 8 |
| 完整 `ps_frame_store` | 1,135 | 1,122 | 18 | 15 |

完整模块保持 827 个触发器、8 个 DSP48E1、344 个分布式 RAM LUT 位置和原有存储容量。
这里的组合级数由寄存器间真实连接计算，器件延迟由完整布局布线时序报告检查。
详细结果见 [容量验证数据](../../docs/data/ps_frame_capacity_validation.json)。
