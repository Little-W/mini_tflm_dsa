# CPU 响应寄存验证

`pico_native_to_axi` 在关闭指令缓存时支持 `REGISTER_RESPONSE`。启用后，AXI 读完成和写响应分别保存为原生接口的一次响应事件，读数据同时进入寄存器。响应等待接收期间不接收新的原生请求。`soc_top` 启用该参数，使 AXI 响应与 CPU 内部控制之间经过寄存器。

默认参数值为零。此时全部控制端口与有效读响应保持原有周期；开启指令缓存的配置保持缓存返回时序。

## 运行方法

```sh
python3 test/pico_response/run_formal.py --out build/pico_response_formal
python3 test/pico_response/run_transactions.py --out build/pico_response_transactions --verilator verilator
```

形式验证检查五组缓存和总线配置的控制状态及有效读数据，并对两组寄存响应配置执行归纳证明。属性包括响应恰好对应上一周期的 AXI 完成事件、读数据正确保存、非读周期数据保持、复位清除响应，以及已保存响应期间禁止重复接收请求。

事务测试使用独立字节存储模型，覆盖地址宽度 32 位和 40 位、数据宽度 32 位和 64 位，以及 `REGISTER_RESPONSE` 的两个取值。读返回和写响应可延迟 0 至 7 个周期，写地址与写数据独立接受背压。寄存模式逐笔检查原生响应与 AXI 完成相隔一个周期。

当前八组事务测试完成 7,284 笔事务，其中读事务 4,146 笔、写事务 3,138 笔；检查 26,608 个读回字节及 48 次复位。读地址、写地址和写数据的等待期间负载稳定检查分别完成 2,084、2,046 和 2,328 次。测试涵盖全部非零字节掩码、连续请求、空闲期间复位及等待期间复位，生成的 C++ 仿真程序启用未定义行为检查。

`formal_validation.json` 和 `transactions_validation.json` 保存源码散列值、参数组合与检查结果。每次运行目录保存固定源码、仿真程序、命令及日志。
