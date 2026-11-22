# 量化运行许可四态检查

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

串行量化保存任务的逐通道配置，在行缓存就绪、同步参数读取完成且参数有效时发射批次。末批发射同时产生行消费事件。初始化使运行许可失效并清空流水状态。

```bash
python test/requant_control_selection/check_four_state.py \
  --source-root . --reference-root <参考源码目录> \
  --out build/requant_control_selection
```

测试从两份实际源码提取运行许可与末批条件，穷举九个控制位的四态组合。逐通道功能启用与禁用分别检查，共 524,288 次比较。完整参数控制和存储检查位于 `test/requant_parameter_ports`；行组装及数值检查位于 `test/requant_time_share`。
