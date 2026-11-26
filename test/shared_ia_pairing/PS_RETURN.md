# 部分和返回存储块选择

`ia_ps_channel_ram` 根据地址与 IA 存储分配独立生成部分和返回块编号。在 `ps_read_fire` 接收读请求的原有时钟边沿保存该编号。物理存储读写使能、地址、写数据、字节掩码、访问冲突和错误状态保持相同。

七个 8 KiB 存储块、生产共享写入与配对端口参数下，部分和读请求至返回选择寄存器的组合级数从 3 降至 2。独立模块由 1,709 LUT 变为 1,710 LUT，触发器保持 12 个，RAMB36 保持 26 个，寄存器间最大组合级数保持 10。

默认参数与生产配对端口参数各完成 8 组时序归纳证明，比较全部物理存储命令、配置状态、同步返回选择和错误输出。首个采样周期复位，后续输入与复位自由。两种模式共完成 131,072 次四态比较，覆盖 2 KiB 和 8 KiB 存储块、6 至 9 个块、两种共享写入阶段、非法配置、地址冲突及 X/Z 输入。

```sh
python test/shared_ia_pairing/run_control.py --source-root . --reference aa246aef --out /tmp/ps_return_generic
python test/shared_ia_pairing/run_control.py --source-root . --reference aa246aef --paired --out /tmp/ps_return_paired
```

`ps_return_validation.json` 与 `ps_return_measurement.json` 保存参数、资源、路径长度及源码和日志校验值。
