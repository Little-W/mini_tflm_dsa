# CPU 访存地址加法

加载与存储指令共用 `memory_address_sum`，以完整 32 位加法计算 `reg_op1 + decoded_imm`。`use_dsp` 属性允许 FPGA 综合器选择算术资源。操作数保存边沿、访存状态、地址定宽回绕和 CPU 执行周期保持。

完整 CPU 状态与公开输出在四种参数配置下通过等价检查，输入未增加限制：生产参数；中断、压缩指令与 64 位计数器；两周期 ALU 与比较器；关闭乘除法的精简寄存器配置。共比较 11,524 个状态及输出位。

```sh
python test/pico_memory_address/run.py --out build/pico_memory_address
```

[validation.json](validation.json) 保存源码、检查程序、参考提交和各配置的 SHA-256 与结果。完整 SoC 功能、资源及路径在固定版本上另外检查。
