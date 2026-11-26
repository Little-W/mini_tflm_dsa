# AXI 突发页边界检查

SoC 存储器根据五种传输尺寸并行计算末拍进位。尺寸字段在最后选择已经完成的跨页结果，完整命令检查同时保留固定突发长度限制和不支持的尺寸、突发类型检查。

在 256 KiB、64 位数据总线、32 位地址和四个在途读写事务的配置下，完整存储器的逻辑 LUT 从 482 增至 501，分布式存储 LUT 为 68，触发器为 198，块存储器为 64 个 RAMB36E1。寄存器之间的最长组合路径保持 9 级。

| 输入至写命令错误状态 | 参考实现组合单元数 | 当前实现组合单元数 |
|---|---:|---:|
| 写地址 | 10 | 8 |
| 突发长度 | 8 | 8 |
| 传输尺寸 | 10 | 4 |
| 突发类型 | 3 | 2 |

输入路径统计从模块输入开始，终止于实际 `wr_cmd_error_q` 寄存器。完整 SoC 还需计入该模块之前的缓冲器组合逻辑。

八组参数完成全部二态输入的 SAT 证明，地址宽度覆盖 8、16、32、40 位，数据宽度覆盖 8 至 512 位。相同配置完成 235,552 次四态比较。实际 RTL 的 AXI 协议测试执行 12 组，覆盖 32/64 位总线、1/3/4 个在途事务、不同存储深度以及随机暂停，全部通过。

```bash
python test/soc_ram_page/run.py --out build/soc_ram_page
python test/conv_soc_ram/run.py --rtl-source rtl/soc/soc_axi_ram.sv --first-read-latencies 2 --synthesis --jobs 1 --out build/soc_ram_page_protocol
```

验证器确认仅命令检查函数发生修改，函数以外的 RTL 与参考版本一致。资源及路径见 `measurement.json`，证明与协议测试见 `validation.json`。
