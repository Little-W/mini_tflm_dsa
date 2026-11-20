# 部分和重放同步存储

`ps_frame_store` 在 `replay_consume` 有效的时钟边沿读取 `decoded_read_pointer` 对应的完整 INT32 行，读取结果与 `replay_valid` 同周期输出。队列保留 8 行，每行 512 位，总容量为 4096 bit。预取最多占用 7 行，读取和写入使用不同的物理位置。复位、配置清除、连续重放和无效周期输出行为保持一致。

存储实例使用 `regfile` 的同步读端口，并指定块存储器类型。生产配置独立综合得到 963 个逻辑 LUT、15 个 RAMB18E1、819 个触发器、2 个 DSP48E1；分布式 RAM LUT 数量为 0。最长寄存器间组合路径为 13 个单元。完整 SoC 的资源和时序以整机报告为准。

## 验证结果

生产 7 银行配置使用相同输入同时驱动参考实现和当前实现，逐周期比较全部 11 项公开输出，包括无效周期数据。663 条帧命令、235696 项 INT32 检查和 31311 个周期通过。7 银行和 9 银行的独立数值检查合计完成 1661 条命令、575840 项 INT32 检查和 76933 个周期，覆盖配置切换、容量限制、连续重放、并行读写和复位。

源码摘要、公开输出列表、数值检查与综合结果保存在 [measurement.json](measurement.json)。

## 执行方法

```sh
python3 test/ps_replay_sync/run_interface.py \
  --reference 653477ed --out build/ps_replay_sync/interface \
  --verilator verilator-modern --profiles 8192:7
python3 test/ps_channels/run_store.py \
  --out build/ps_replay_sync/numeric --profiles 8192:7 8192:9
python3 test/ps_channels/synthesis.py \
  --out build/ps_replay_sync/synthesis --kind store --layout fixed
```
