// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 向量执行控制的状态编码与同拍保存的状态资格。
package vector_engine_control_pkg;
  typedef enum logic [5:0] {
    IDLE, CHECK, CONFIGURE, TILE_INIT, LOAD_REQ, LOAD_WAIT,
    OUTPUT_INIT, TAP_CHECK, WINDOW_WAIT, EXECUTE, TAP_NEXT,
    QUANT_INIT, AVG_START, AVG_WAIT, POOL_STORE, WRITE_PREP,
    OUTPUT_NEXT, VECTOR_INIT, VECTOR_NEXT, VECTOR_REDUCE, FAILED, DONE,
    ADD_MULT, ADD_DRAIN, ADD_ROUND, ADD_SUM, ADD_STORE,
    POOL_LOAD_PREP, POOL_LOAD_REQ, POOL_LOAD_WAIT,
    DRAIN, DRAIN_TILE, SOFT_START, SOFT_RUN, SOFT_LUT_REQ, SOFT_LUT_WAIT,
    CHECK_WAIT, EXECUTE_COMMIT = 6'd38, ADD_ROUND_WAIT, AVG_POWER_STORE, POOL_LOAD_DRAIN,
    DW_EXECUTE, DW_FINISH, ADD_CLAMP, AVG_POWER_DELAY, AVG_POWER_CLAMP, LOAD_VERIFY
  } state_t;
  typedef enum logic [2:0] {LD_WEIGHT, LD_BIAS, LD_MULT, LD_SHIFT, LD_A, LD_B, LD_LUT} load_t;
  // 握手、执行和权重地址归零资格同状态一起保存，状态保持时也保持这些寄存输出。
  function automatic logic [$bits(state_t)+13:0] state_control_value(input state_t next_state);
    state_control_value = {
        (next_state==OUTPUT_INIT || next_state==DW_FINISH),
        (next_state==OUTPUT_INIT || next_state==DW_EXECUTE || next_state==DW_FINISH),
        next_state==DW_EXECUTE,
        next_state==POOL_STORE,
        next_state==OUTPUT_INIT,
        next_state==VECTOR_INIT,
        next_state==DW_FINISH,
        next_state==EXECUTE_COMMIT,
        next_state==FAILED,
        (next_state==OUTPUT_INIT || next_state==TAP_CHECK || next_state==WINDOW_WAIT || next_state==EXECUTE || next_state==EXECUTE_COMMIT || next_state==TAP_NEXT || next_state==QUANT_INIT || next_state==OUTPUT_NEXT || next_state==AVG_START || next_state==AVG_POWER_DELAY || next_state==AVG_POWER_CLAMP || next_state==AVG_POWER_STORE || next_state==AVG_WAIT || next_state==POOL_STORE || next_state==WRITE_PREP || next_state==DW_EXECUTE || next_state==DW_FINISH),
        next_state==CONFIGURE,
        next_state==LOAD_REQ || next_state==POOL_LOAD_REQ || next_state==SOFT_LUT_REQ,
        next_state==IDLE,
        next_state==DONE,
        next_state
    };
  endfunction
endpackage

`default_nettype wire
