# 普通任务完成握手

本测试实例化真实 `npu_top`，使用 16×16 计算阵列、64 位 AXI、8 个 4 KiB 共享存储块及默认 `OPERAND_CACHE_ENABLE=0`。计算和内存模型来自 `test/conv_npu`；完成时序由本目录的独立测试控制，公共性能测试脚本保持原有行为。

每次仿真连续执行 INT8 GEMM、普通卷积、INT16 GEMM、普通卷积，覆盖 WS 与 IS 数据流。每个任务完成之前保持 `done_ready=0`，确认普通控制器进入 `WAIT_DONE`，检查背压期间 `done_valid` 和错误码稳定。随后保持 `done_ready=1` 共 24 个周期，逐周期检查该任务仅被接受一次，并在接收后撤销 `done_valid`。

每个完成响应都要求物理 DMA、卷积后台读取及操作数预取已经排空。下一个任务继续使用同一实例，检查配置切换与运行恢复。所有任务同时检查 INT32 累加值、量化输出、完整内存内容、输入读取范围和输出保护区域。固定 AXI 延迟与随机地址、数据背压分别运行一次。

```sh
python3 test/completion_handshake/run.py \
  --verilator "$VERILATOR_BIN" --jobs 1 \
  --out build/completion_handshake
```

运行目录必须位于仓库内，以便统一保存相对源码路径。`build.json` 保存源码摘要、编译参数和二进制摘要；`summary.json` 保存每个任务的完成接收数量、持续就绪周期、计算检查数量及日志摘要。
