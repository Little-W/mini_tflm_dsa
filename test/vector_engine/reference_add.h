/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VECTOR_ENGINE_REFERENCE_ADD_H
#define VECTOR_ENGINE_REFERENCE_ADD_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    int32_t input1_offset, input2_offset;
    int32_t input1_multiplier, input1_shift;
    int32_t input2_multiplier, input2_shift;
    int32_t left_shift;
    int32_t output_multiplier, output_shift;
    int32_t output_offset, activation_min, activation_max;
} vector_add_reference_params;
int vector_add_reference(const vector_add_reference_params *params,
                         uint32_t length, const int8_t *input1,
                         const int8_t *input2, int8_t *output);
#ifdef __cplusplus
}
#endif
#endif
