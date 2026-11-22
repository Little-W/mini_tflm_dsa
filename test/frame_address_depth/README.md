# 帧地址流水线验证

`frame_address_prepare` 复用一个十七位无符号部分积运算器与三十二位累加器。默认配置独立寄存乘积，地址结果在 11 个周期后有效，NPU 在命令接收后的第 12 个周期开始执行。

当前功能验证入口：

```sh
python test/frame_address/run.py --out build/frame_address/numeric --pipeline-products 1
python test/frame_address/run_formal.py --out build/frame_address/formal
```

数值测试使用完整三十二位地址公式，检查普通和分块布局、两种数据流、INT8/INT16、复位、中止及结果等待。形式验证使用任意符号部分积检查流水控制，并证明地址拆分恒等式和六种分块大小的地址表达式。

本目录的 `run_formal.py` 用于相同流水配置的版本间状态比较，`--reference-ref` 指定参考提交。`prepare_measurement.py` 生成独立模块的资源与路径测量输入。整机资源和时序使用完整 SoC 的测量结果。
