# 快速开始

## 获取源码

```bash
git clone --recurse-submodules <repository-url>
cd tflm_ai_dsa
```

已有工作目录可执行 `git submodule update --init --recursive`。PicoRV32 的版本由仓库中的子模块提交固定，SoC 仿真与 FPGA 工程读取 `picorv32/` 中的处理器及 UART 源码。

## 环境

模块和 SoC 仿真使用 Synopsys VCS；SoC 固件构建需要 RISC-V 交叉编译器。Python 仿真接口需要 Python 3、NumPy 和 Verilator；FPGA 工程需要 AMD Vivado。具体工具与配置见 [仿真与 FPGA](verification.md)。

## 模型与仿真

在仓库根目录运行：

```bash
make model-list
make model-select MODEL=mnist_mlp_int16x8
make model-build
make vcs-tflm
```

`make model-select` 在未指定 `MODEL` 时提供编号菜单。模块测试可使用 `make vcs-unit`，查看其他命令可运行 `make help`。模型及软件接口见 [软件与模型](software.md)。
