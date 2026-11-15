/* Copyright 2023 The TensorFlow Authors. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
==============================================================================*/

#include "tensorflow/lite/kernels/internal/common.h"

namespace tflite {

namespace {
int32_t SaturateInt32(int64_t value) {
  return static_cast<int32_t>(std::max<int64_t>(INT32_MIN,
      std::min<int64_t>(INT32_MAX, value)));
}
}  // namespace

int32_t MultiplyByQuantizedMultiplier(int32_t x, int32_t multiplier, int shift) {
  TFLITE_DCHECK(shift >= -31 && shift <= 30);
  return SaturateInt32(gemmlowp::RoundingDivideByPOTInt64(
      static_cast<int64_t>(x) * multiplier, 31 - shift));
}

// Q31 multiplication with a 96-bit unsigned magnitude. No reduced coefficient
// or intermediate rounding is used; the final result saturates to int32.
int32_t MultiplyByQuantizedMultiplier(int64_t x, int32_t multiplier, int shift) {
  TFLITE_DCHECK(shift >= -31 && shift <= 30);
  const bool negative = (x < 0) != (multiplier < 0);
  const uint64_t magnitude = x < 0 ? uint64_t(0) - static_cast<uint64_t>(x)
                                  : static_cast<uint64_t>(x);
  const uint32_t factor = multiplier < 0 ? uint32_t(0) - static_cast<uint32_t>(multiplier)
                                         : static_cast<uint32_t>(multiplier);
  const uint64_t low = uint64_t(static_cast<uint32_t>(magnitude)) * factor;
  const uint64_t high = (magnitude >> 32) * factor + (low >> 32);
  const uint32_t words[3] = {static_cast<uint32_t>(low),
                            static_cast<uint32_t>(high), static_cast<uint32_t>(high >> 32)};
  const int right = 31 - shift;
  uint64_t quotient = 0;
  for (int bit = 95; bit >= right; --bit) {
    if ((words[bit / 32] >> (bit % 32)) & 1u) {
      if (bit - right >= 32) return negative ? INT32_MIN : INT32_MAX;
      quotient |= uint64_t(1) << (bit - right);
    }
  }
  const bool half = ((words[(right - 1) / 32] >> ((right - 1) % 32)) & 1u) != 0;
  bool remainder = false;
  for (int bit = right - 2; bit >= 0; --bit)
    remainder |= ((words[bit / 32] >> (bit % 32)) & 1u) != 0;
  quotient += half && (remainder || (quotient & 1u));
  const uint64_t limit = negative ? uint64_t(1) << 31 : INT32_MAX;
  if (quotient >= limit) return negative ? INT32_MIN : INT32_MAX;
  return negative ? -static_cast<int32_t>(quotient) : static_cast<int32_t>(quotient);
}

}  // namespace tflite
