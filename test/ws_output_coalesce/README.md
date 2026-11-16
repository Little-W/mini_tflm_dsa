# WS 输出合并验证

测试通过完整 AXI-Lite 接口运行矩阵任务，使用 Python 整数点积和最近偶数舍入计算参考结果。每项检查输出张量、其他全部外部内存、严格张量读取范围、写入范围、AXI 背压稳定性及完成时的事务状态。

WS 输出组覆盖完整行、行尾部、少于 R 个 row tile 的末组、多列片段、多行组、非整数倍地址和 4 KiB 页边界。输出 FIFO 的专项断言检查每次合并读取对应已经发布的 bank，并且行索引位于实际写入范围内。结果记录写请求数、数据拍数、最大写突发和实际 row tile 数。

输入包括普通和 packed 布局、非零零点、逐通道和逐张量量化、S16 输入与 S16 输出、固定和随机 AXI 等待、写响应错误、读响应错误及后续任务。S16 FIFO 使用 4 个 bank，并通过持续写背压检查容量使用。

```bash
python3 test/ws_output_coalesce/run.py \
  --out build/ws_output_coalesce --profiles 8 16 \
  --verilator "$VERILATOR" --jobs 2

python3 test/ws_output_coalesce/run.py \
  --out build/ws_output_coalesce_ws_only --profiles 8 --ws-only \
  --verilator "$VERILATOR" --jobs 2

python3 test/ws_output_coalesce/small_banks.py \
  --out build/ws_output_small_banks --verilator "$VERILATOR" --jobs 2
```

配置固定为 `SIZE=16`、`PS_STORAGE_ROWS=799`、`OA_S16_FIFO_BANKS_MAX=4`。关闭 IS 硬件时使用线性 S8 FIFO，测试仍检查相同数学结果和内存访问范围。

`small_banks.py` 另外构建 `IA_CACHE_BLOCKS=2`、`PS_FRAME_COUNT=1/2` 的完整 NPU 实例，使 S8 FIFO 分别具有 1/2 个 bank。两种配置分别执行 8 个矩阵形状的固定和随机等待测试，检查小容量下的调度完成与输出结果。
