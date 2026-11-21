# 输出 FIFO 的银行选择

写入位置同时保存二进制索引和独热索引。接收当前银行的结束标记时，两种索引在同一时钟边沿前进；银行被占用时保持。当前银行和下一银行的阻塞条件使用独热选择与归约计算，支持一个银行及非二次幂银行数量。

`run_formal.py` 先对实际指针更新建立复位后的无界归纳证明，再将已证明的状态关系用于完整 FIFO 比较。比较内容包括全部公开输出、存储读写地址、使能、写数据和有效银行计数。九组参数覆盖 1、2、3、8、16、32、64 个银行、32/64 位总线和两种存储排列方式，公开输入与存储返回值没有附加限制。

`run_four_state.py` 使用实际更新过程和选择表达式，检查 20,000 个周期中的 X/Z 控制位、银行状态、复位、二进制位置、独热位置及消费端阻塞条件，共完成 560,000 次比较。

```bash
python test/fifo_write_pointer/run_formal.py --out build/fifo_pointer_formal
python test/fifo_write_pointer/run_four_state.py --out build/fifo_pointer_four_state
```

实际源码散列值与结果保存在 `validation.json`。
