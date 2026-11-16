/* SPDX-License-Identifier: Apache-2.0 */
#ifndef TENSORFLOW_LITE_MICRO_KERNELS_SOFTMAX_VCE_H_
#define TENSORFLOW_LITE_MICRO_KERNELS_SOFTMAX_VCE_H_

#include "fixedpoint/fixedpoint.h"
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/kernels/internal/types.h"

namespace tflite {

inline void PopulateSoftmaxVceTable(const SoftmaxParams& params, int32_t* table) {
  using ScaledDiff = gemmlowp::FixedPoint<int32_t, 5>;
  for (int distance=0;distance<256;distance++) {
    const int32_t difference=-distance;
    if (difference<params.diff_min) table[distance]=0;
    else {
      const int32_t scaled=MultiplyByQuantizedMultiplierGreaterThanOne(
          difference,params.input_multiplier,params.input_left_shift);
      table[distance]=gemmlowp::exp_on_negative_values(ScaledDiff::FromRaw(scaled)).raw();
    }
  }
}

}  // namespace tflite
#endif
