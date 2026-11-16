/* SPDX-License-Identifier: Apache-2.0 */
#include <cassert>
#include <cstdint>
#include "dsa_accel.h"
#include "riscv_nn_prepared.h"

uint32_t prepared_result = DSA_SUCCESS;
unsigned prepared_calls;
const void* prepared_input;
void* prepared_output;

extern "C" void dsa_prepared_invalidate(dsa_prepared_t* prepared) {
  if (prepared) prepared->valid = 0u;
}

extern "C" uint32_t dsa_prepare_conv_s8(dsa_prepared_t* prepared,
                                       const dsa_conv_s8_config_t*) {
  dsa_prepared_invalidate(prepared);
  return DSA_ERR_UNSUPPORTED;
}

extern "C" uint32_t dsa_prepare_spatial_s8(dsa_prepared_t* prepared,
                                          const dsa_vector_config_t*) {
  dsa_prepared_invalidate(prepared);
  return DSA_ERR_UNSUPPORTED;
}

extern "C" uint32_t dsa_prepare_matmul_s8(dsa_prepared_t* prepared,
                                         const dsa_prepared_matmul_s8_config_t*) {
  dsa_prepared_invalidate(prepared);
  return DSA_ERR_UNSUPPORTED;
}

extern "C" uint32_t dsa_prepared_execute(const dsa_prepared_t* prepared,
                                        const void* input, void* output) {
  assert(prepared && prepared->valid == DSA_PREPARED_VALID);
  ++prepared_calls;
  prepared_input = input;
  prepared_output = output;
  return prepared_result;
}

extern "C" void dsa_matrix_query(dsa_matrix_limits_t* limits) {
  assert(limits);
  *limits = {};
}
