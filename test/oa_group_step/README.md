# 输出写回组步长

`oa_writer` 将幂次复用数量编码为三位移位量，共用行地址步长移位器。25倍步长使用定宽加法，较小计数位宽保留常量截断后的选择优先级。地址、命令、队列握手和完成时刻保持一致。

生产配置为16列、64位AXI和29位计数。独立综合使用1,469个逻辑LUT、780个触发器和155个CARRY4，最长组合路径为15级。相同工具与参数下，修改前使用1,523个逻辑LUT，其余上述数量相同。

形式验证覆盖8组列数、总线宽度及计数位宽，比较12,520位公开输出与状态，全部输入不附加约束。接口仿真覆盖3组参数、1,536个场景和1,552,037个周期，逐周期比较全部21项输出。

```sh
python test/oa_group_step/run_formal.py \
  --out build/oa_group_step/formal --synthesis
python test/oa_writer/run_equivalence.py --reference 864d659c \
  --out build/oa_group_step/interface --verilator verilator-modern \
  --profiles 16:64:29 16:32:6 4:32:8
```

具体结果、源文件摘要和日志摘要见 `measurement.json`。
