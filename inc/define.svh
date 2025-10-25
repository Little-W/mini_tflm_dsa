`ifndef DEFINE_SVH
`define DEFINE_SVH
`define E203_ADDR_SIZE 32
`define E203_XLEN 32
`define E203_XLEN_MW (`E203_XLEN / 8)
`define SA_SIZE 16
`define ICB_LEN_W $clog2(`SA_SIZE)
`endif