/* SPDX-License-Identifier: Apache-2.0 */
#include "reference_add.h"
#include <limits.h>

static int64_t round_quotient_even(int64_t numerator, int64_t denominator)
{
    int64_t quotient = numerator / denominator;
    const int64_t remainder = numerator % denominator;
    const int64_t magnitude = remainder < 0 ? -remainder : remainder;
    if (magnitude > denominator - magnitude ||
        (magnitude == denominator - magnitude && quotient % 2 != 0))
        quotient += numerator < 0 ? -1 : 1;
    return quotient;
}

static int64_t scale(int64_t input, int32_t multiplier, int32_t shift)
{
    return round_quotient_even(input * multiplier, INT64_C(1) << (31 - shift));
}

int vector_add_reference(const vector_add_reference_params *p,
                         uint32_t length, const int8_t *input1,
                         const int8_t *input2, int8_t *output)
{
    if (!p || !input1 || !input2 || !output || length == 0 ||
        p->input1_offset < -127 || p->input1_offset > 128 ||
        p->input2_offset < -127 || p->input2_offset > 128 ||
        p->input1_multiplier < 0 || p->input2_multiplier < 0 ||
        p->output_multiplier < 0 || p->input1_shift < -31 ||
        p->input1_shift > 0 || p->input2_shift < -31 || p->input2_shift > 0 ||
        p->left_shift < 0 || p->left_shift > 22 ||
        p->output_shift < -31 || p->output_shift > 30 ||
        p->output_offset < -128 || p->output_offset > 127 ||
        p->activation_min < -128 || p->activation_max > 127 ||
        p->activation_min > p->activation_max)
        return -1;
    const int64_t factor = INT64_C(1) << p->left_shift;
    for (uint32_t i = 0; i < length; ++i) {
        const int64_t a = ((int64_t)input1[i] + p->input1_offset) * factor;
        const int64_t b = ((int64_t)input2[i] + p->input2_offset) * factor;
        const int64_t sa = scale(a, p->input1_multiplier, p->input1_shift);
        const int64_t sb = scale(b, p->input2_multiplier, p->input2_shift);
        if (sa + sb < INT32_MIN || sa + sb > INT32_MAX) return -1;
        int64_t value = scale(sa + sb, p->output_multiplier, p->output_shift);
        value += p->output_offset;
        if (value < p->activation_min) value = p->activation_min;
        if (value > p->activation_max) value = p->activation_max;
        output[i] = (int8_t)value;
    }
    return 0;
}
