// SPDX-License-Identifier: Apache-2.0
package conv_im2col_frontend_pkg;
  typedef enum logic [22:0] {
    IDLE = 23'h000001,
    P_DECODE = 23'h000002,
    P_START = 23'h000004,
    P_WAIT = 23'h000008,
    Q_DECODE = 23'h000010,
    Q_START = 23'h000020,
    Q_WAIT = 23'h000040,
    K_DECODE = 23'h000080,
    K_START = 23'h000100,
    K_WAIT = 23'h000200,
    COORD = 23'h000400,
    COORD_SUM = 23'h000800,
    COORD_PAD = 23'h001000,
    ADDRESS = 23'h002000,
    ADDRESS_PIXEL = 23'h004000,
    ADDRESS_PRODUCT = 23'h008000,
    ADDRESS_BASE = 23'h010000,
    ADDRESS_CHANNEL = 23'h020000,
    FETCH = 23'h040000,
    WAIT_WORD = 23'h080000,
    STREAM = 23'h100000,
    ZERO_STREAM = 23'h200000,
    DESCRIPTOR_CHECK = 23'h400000
  } st_t;
endpackage
