# 普通 im2col 描述符与后台预取

普通 im2col 命令在 DMA 接收边沿保存 `p0`、`q0`、`group`、行数、列数、槽编号和标签。合法命令置位 `conv_pending`，前端在后续就绪边沿接收保存的描述符。前端已经就绪时，接收间隔为一个周期；等待期间各字段保持稳定。

## 完成与排空

描述符完成表示其矩阵元素已经全部返回。缓存后台预取可以继续运行，下一条同配置 im2col 描述符可以同时启动。`rd_busy` 与 `conv_busy` 持续反映缓存、读取保护器和读取复用器的实际活动。

切换到线性读取、更新图像配置以及报告整层完成时，需要先等待实际读取结束。顶层同时限制完成有效信号和完成接收信号，使控制器在排空期间保持完成状态。最后一个线性返回拍仍允许接收下一条图像描述符，返回数据按生产者有效信号及原描述符标签分配。

中止阻止新的描述符接收，已经接收的事务继续执行并排空。复位取消在途事务；非法描述符通过完成接口报告一次错误。窗口队列与普通描述符具有独立的占用状态。

## 功能检查

默认测试直接运行通用 RTL，并启用断言和 C++ 未定义行为检查。`--fpga` 使用官方 FPGA 原语功能模型。测试覆盖非规则 `q0`、非对齐起址、4 KiB 边界、地址与数据背压、读取错误、中止、复位恢复、连续图像命令，以及线性与图像命令交替执行。

AXI64 配置的当前结果如下。

| 检查项目 | 数量 |
| --- | ---: |
| 场景 | 191 |
| 接收描述符 | 192 |
| 完成描述符 | 191 |
| 复位取消描述符 | 1 |
| 逐元素比较 | 10,602 |
| 后台预取期间接收图像描述符 | 40 |
| 描述符完成时后台预取仍在运行 | 36 |
| 错误完成 | 7 |
| 线性最后返回拍与图像接收同时发生 | 1 |

延迟返回场景将首拍延迟设置为 32 个周期，检查后续图像分块可继续处理，同时确认线性命令等待图像读取结束。每条合法前端请求均在已保存描述符的下一周期启动。

## 复现

```sh
python3 test/dma_registered_issue/run.py --bus-width 64 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/control64
python3 test/dma_registered_issue/run.py --bus-width 32 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/control32
python3 test/dma_registered_issue/run.py --bus-width 64 --cache-blocks 1 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/control64_slot1
```

每次运行保存源码 SHA-256、程序 SHA-256、实际编译命令、参数和检查数量，结果记录于指定目录的 `summary.json`。
