# 共享权重写请求资格

`vector_shared_store` 的 `p_weight_nonempty_writes` 参数使用生产者保存的有效写请求。`vector_engine_operand_store` 在同一边沿保存非空字节掩码和有效状态，因此后级直接使用有效位即可。通用参数默认关闭。未知有效位继续使用完整掩码归并表达式，专用模式的实际生产连接具有非空掩码断言。

## 资源与组合级数

七个 8 KiB 存储块、固定 PS 通道、普通 RTL 推断和相同映射选项下，访问资格模块由 38 LUT 减少到 31 LUT，触发器保持 7 个，寄存器间最大组合级数保持 4。写掩码到请求有效信号的重复归并已由同拍保存的有效状态替代。

## 检查结果

- 实际完整 `vector_engine_operand_store` 的通用与综合编译模式均完成时序归纳证明。全部外部输入自由，观察到复位边沿后，有效权重写请求必有已置位的字节掩码。
- 实际 `vector_shared_store` 的默认模式和专用模式共 8 组参数完成所有输出及全部状态的时序归纳证明。专用模式使用非空写请求这一生产者性质，其他输入自由。
- 两种模式各完成 12 组参数、4,096 个四态周期及 3,047,424 次输出比较，包含 X/Z 控制、地址、数据、掩码，以及同址冲突、非法配置和清空。
- 实际生产 C 驱动、AXI-Lite 顶层和外部存储模型分别执行固定与随机 AXI 延迟配置，每种配置通过 104 项测试和 52,214 个输出检查。覆盖卷积、矩阵、深度卷积、池化、向量算术、任务交替和共享存储错误恢复。
- 系统测试同时检查已启用的共享 IA 配对端口性质以及向量有效写请求的非空掩码性质。

## 运行

```sh
python test/vector_weight_qualification/run_nonempty.py --source-root . --out /tmp/vector_weight_nonempty
python test/vector_weight_qualification/run_shared_request.py --source-root . --out /tmp/vector_shared_request
python test/vector_weight_qualification/run_shared_system.py --out /tmp/vector_shared_system --verilator verilator --jobs 2
```

`shared_request_validation.json` 与 `shared_request_measurement.json` 记录参数、结果和源码校验值。
