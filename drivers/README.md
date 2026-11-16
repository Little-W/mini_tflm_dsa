# DSA AXI/MMIO 加速器驱动

## 概述

本驱动提供 AXI 外设的 C 语言接口，支持：

- MMIO 寄存器访问
- 矩阵乘法启动、轮询和 WS/IS 自动调度
- 逐张量和逐通道量化
- INT8 输入、INT8 权重、INT8 输出，以及 INT16 输入、INT8 权重、INT16 输出；偏置使用 INT32

## 文件说明

- `dsa_accel.h` - 驱动头文件，定义所有接口
- `dsa_accel.c` - 驱动实现文件
- `dsa_matrix.h` - 矩阵能力查询与 16×16 数据排列
- `dsa_schedule.h` - WS/IS 数据流、复用参数与传输成本计算
- `registers_v2.md` - 新版 AXI/MMIO 寄存器说明

## 自动矩阵调度与 AXI64

将 `dataflow_mode` 设为 `DSA_DATAFLOW_AUTO`，并将 `ia_reuse_num`、`w_reuse_num` 设为 0，驱动会在硬件容量允许的候选中计算 WS/IS 数据流及复用参数。`dsa_matmul_plan()` 可在启动前返回所选数据流、分组、物理总线数据拍数和预计周期。指定数据流时保持该选择；非零复用参数作为搜索上限。

评分分别计算读数据传输、写数据传输、阵列计算和 IA 输入调度所需的时间。IA 调度估计包含流式操作数读取与驻留操作数装载，最后取各项最大值。输入和权重的行跨度、起始地址余数、尾部尺寸与分块排列都会影响数据拍及事务数量。`veri/top_regression/host_schedule.py` 提供相同的 Python 算法。

`dsa_matrix_query()` 从 `0x0f0` 读取 DMA 最大突发字节数，从 `0x0f4` 读取物理 AXI 数据宽度。AXI64 每拍 8 B，完整突发最多 256 拍、2,048 B，并在 4 KiB 边界拆分。AXI32 每拍 4 B，最多 1,024 B。配置 MMIO 仍使用 32 位访问。

调度结果中的 `read_beats`、`write_beats` 使用物理 AXI 数据拍，`read_words`、`write_words` 使用 32 位字。平台需按实际连续传输能力设置 `DSA_SCHEDULE_READ_BEAT_CYCLES`；同步 RAM 能够每周期返回一拍时，构建驱动使用：

```sh
riscv64-unknown-elf-gcc -march=rv32im -mabi=ilp32 \
  -DDSA_SCHEDULE_READ_BEAT_CYCLES=1 -c dsa_accel.c -o dsa_accel.o
```

首拍延迟按每个已接受请求计算，可由 outstanding 请求和突发传输重叠隐藏。数据拍间隔、DMA 最大突发长度与首拍延迟分别描述吞吐、事务大小和请求等待时间。

## 寄存器文档

新版外设的详细寄存器定义见 [registers_v2.md](registers_v2.md)。文档按基地址、控制/状态位、矩阵配置寄存器和访问顺序整理，适合驱动联调时直接查阅。

## 使用示例

### 1. 基本矩阵乘法（Per-Tensor量化）

```c
#include "dsa_accel.h"

int8_t A[128 * 256];  // K=128, N=256
int8_t B[256 * 64];   // N=256, M=64, column-major
int8_t C[128 * 64];   // K=128, M=64
int32_t bias[64];     // M=64

dsa_matmul_config_t config;
dsa_matmul_config_init(&config);

config.lhs_ptr = (uint32_t)(uintptr_t)A;
config.rhs_ptr = (uint32_t)(uintptr_t)B;
config.dst_ptr = (uint32_t)(uintptr_t)C;
config.bias_ptr = (uint32_t)(uintptr_t)bias;

config.K = 128;
config.N = 256;
config.M = 64;
config.lhs_row_stride = 256;  // 每行 256 字节
config.rhs_row_stride = 256;  // 每列 256 字节
config.dst_row_stride = 64;   // 每行 64 字节

config.lhs_offset = 128;  // 零点偏移
config.dst_mult = 1234567;
config.dst_shift = 10;

uint32_t status = dsa_matmul_execute(&config);
if (status != DSA_SUCCESS) {
    // 错误处理
}
```

### 2. Per-Channel量化

```c
int32_t mult_per_ch[64];   // 每通道mult
int32_t shift_per_ch[64];  // 每通道shift

dsa_matmul_config_init(&config);
// ...existing code...

config.quant_mode = DSA_QUANT_PER_CHANNEL;
config.dst_mult_ptr = (uint32_t)(uintptr_t)mult_per_ch;
config.dst_shift_ptr = (uint32_t)(uintptr_t)shift_per_ch;

uint32_t status = dsa_matmul_execute(&config);
```

### 3. 底层 MMIO 直接访问

```c
// 写入寄存器
dsa_reg_write(NPU_REG_LHS_BASE, (uint32_t)(uintptr_t)A);

// 读取寄存器
uint32_t value = dsa_reg_read(NPU_REG_K);

// 直接调用高层 API
uint32_t status = dsa_matmul_execute(&config);
```

## 返回状态码

- `DSA_SUCCESS (0x00000000)` - 执行成功
- `DSA_ERR_NULL_PTR (0x00000002)` - 必需指针为空
- `DSA_ERR_INVALID_DIM (0x00000003)` - 尺寸、数据类型或容量配置不满足要求

## 编译说明

```bash
riscv64-unknown-elf-gcc -march=rv32im -mabi=ilp32 -c dsa_accel.c -o dsa_accel.o
```

## 注意事项

1. `DSA_MMIO_BASE` 当前与 `soc_top.sv` 保持一致，为 `0x10000000u`
2. 配置结构中的地址字段是 RV32 物理地址值，赋值时使用 `(uint32_t)(uintptr_t)ptr`
3. Per-channel模式下，mult/shift数组长度必须等于M
4. 激活范围需根据输出数据类型合理设置
5. 步进值按字节配置；当前 SoC 回归使用显式 stride
