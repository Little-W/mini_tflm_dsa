/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>
#include <stddef.h>
#include <limits.h>

static int64_t divide_even(int64_t value, int64_t divisor)
{
    int64_t quotient = value / divisor;
    const int64_t remainder = value % divisor;
    const int64_t magnitude = remainder < 0 ? -remainder : remainder;
    if (magnitude > divisor - magnitude ||
        (magnitude == divisor - magnitude && quotient % 2 != 0))
        quotient += value < 0 ? -1 : 1;
    return quotient;
}

int vector_engine_reference(const uint32_t *c, const int8_t *input, const int8_t *weight,
                      const int32_t *bias, int32_t *mult, int32_t *shift, int8_t *output)
{
    const unsigned op = c[0] & 15u;
    if (op > 3) return -1;
    for (uint32_t oy = 0; oy < c[16]; ++oy)
        for (uint32_t ox = 0; ox < c[17]; ++ox)
            for (uint32_t ch = 0; ch < c[13]; ++ch) {
                int64_t sum = op == 0 && bias ? bias[ch] : 0;
                int32_t best = op == 2 ? INT8_MIN : INT8_MAX;
                uint32_t count = 0;
                for (uint32_t ky = 0; ky < c[14]; ++ky)
                    for (uint32_t kx = 0; kx < c[15]; ++kx) {
                        const int64_t y = (int64_t)oy*c[18] - c[22] + (int64_t)ky*c[20];
                        const int64_t x = (int64_t)ox*c[19] - c[23] + (int64_t)kx*c[21];
                        if (y < 0 || x < 0 || y >= c[11] || x >= c[12]) continue;
                        const int32_t value = input[((size_t)y*c[12] + (size_t)x)*c[13] + ch];
                        if (op == 0) sum += (int64_t)(value + (int32_t)c[24]) * weight[((size_t)ky*c[15] + kx)*c[13] + ch];
                        else sum += value;
                        if ((op == 2 && value > best) || (op == 3 && value < best)) best = value;
                        ++count;
                    }
                int64_t value;
                if (op == 0) {
                    if (mult[ch] < 0 || shift[ch] < -31 || shift[ch] > 30) return -1;
                    int64_t wrapped = (uint32_t)sum;
                    if (wrapped > INT32_MAX) wrapped -= INT64_C(1) << 32;
                    value = divide_even(wrapped * mult[ch], INT64_C(1) << (31 - shift[ch]));
                    value += (int32_t)c[8];
                } else {
                    if (count == 0) return -1;
                    value = op == 1 ? divide_even(sum, count) : best;
                }
                if (value < (int32_t)c[9]) value = (int32_t)c[9];
                if (value > (int32_t)c[10]) value = (int32_t)c[10];
                output[((size_t)oy*c[17] + ox)*c[13] + ch] = (int8_t)value;
            }
    return 0;
}
