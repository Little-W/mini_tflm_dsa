# 向量结果写入队列验证

`run.py` 对 `vector_writeback` 执行 AXI32 和 AXI64 两组独立 RTL 仿真。每组包含 256 次结果请求，所有接收字节均与模拟内存中的实际写入逐项比较。

```bash
python3 test/vector_writeback/run.py --verilator /path/to/verilator --jobs 2
```

测试包含以下内容：

- 连续的 16 个八字节结果合并为两个六十四字节突发。
- 随机长度的 INT8 结果与 INT32 结果共享写入队列。
- 未按总线字节数对齐的起始地址、地址不连续和部分字节写入。
- 写入地址、数据及响应的随机等待，检查停顿期间数据和字节使能保持不变。
- 结果接收后立即改变输入数据，检查已接收数据仍能正确发送。
- 写入响应错误的传递，以及强制发送尚未填满的队列。
- 每个有效输出字节恰好写入一次，完成时所有写入响应均已返回。

结果保存在 `build/vector_writeback/summary.json`，其中包含两种总线宽度的请求次数、字节数、事务数、响应数、错误响应数和源文件 SHA-256。

## 逐周期 A/B 对照

`miter.sv` 同时实例化当前 RTL 与由调用者提供的基线模块
`vector_writeback_baseline`。测试覆盖 AXI32/64、随机等待、错误、flush、
连续和不连续地址（起点接近 4K 边界），在有效周期比较控制、完整数据及 mask。
它比较原实现行为，不证明实现符合 4K 突发规则；Verilator 是两态模拟。
例如，将基线复制并重命名到临时目录后运行：

```bash
sed 's/module vector_writeback #(/module vector_writeback_baseline #(/' "$BASELINE" > /tmp/vector_writeback_baseline.sv
for w in 32 64; do
  verilator --binary --timing --top-module miter -Wno-fatal -GBUS_WIDTH=$w \
    --Mdir /tmp/vector_writeback_miter_$w test/vector_writeback/miter.sv \
    rtl/npu/conv/vector_writeback.sv /tmp/vector_writeback_baseline.sv
  /tmp/vector_writeback_miter_$w/Vmiter
done
```

`ab_synth.tcl` 在 xc7a200tfbg484-3 上以默认参数执行独立模块综合：
`vivado -mode batch -source test/vector_writeback/ab_synth.tcl -tclargs <RTL路径> <报告路径>`。
两次比较须使用相同工具和参数；独立模块结果不能直接等同整设计层级面积，
该脚本也不提供有效的约束时序比较。
