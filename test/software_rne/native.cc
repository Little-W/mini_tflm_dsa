/* SPDX-License-Identifier: Apache-2.0 */
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/add.h"
#include "tensorflow/lite/kernels/internal/reference/softmax.h"
#include "tensorflow/lite/kernels/internal/quantization_util.h"
extern "C" {
int32_t check_tflm_requant(int32_t x,int32_t m,int s) { return tflite::MultiplyByQuantizedMultiplier(x,m,s); }
int32_t check_tflm_s64(int64_t x,int32_t m,int s) { return tflite::MultiplyByQuantizedMultiplier(x,m,s); }
int32_t check_gemm_high(int32_t a,int32_t b) { return gemmlowp::SaturatingRoundingDoublingHighMul(a,b); }
int32_t check_gemm_half(int32_t a,int32_t b) { return gemmlowp::RoundingHalfSum(a,b); }
int32_t check_gemm_divide(int32_t a,int s) { return gemmlowp::RoundingDivideByPOT(a,s); }
int64_t check_gemm_divide64(int64_t a,int s) { return gemmlowp::RoundingDivideByPOTInt64(a,s); }
double check_tflm_round(double a) { return tflite::TfLiteRound(a); }
void check_quantize(double a,int32_t *m,int *s) { tflite::QuantizeMultiplier(a,m,s); }
void check_tflm_add(const int32_t *q,const int8_t *a,const int8_t *b,int8_t *out,int n) {
  tflite::ArithmeticParams p = {};
  p.input1_offset=q[0]; p.input2_offset=q[1]; p.input1_multiplier=q[2]; p.input1_shift=q[3];
  p.input2_multiplier=q[4]; p.input2_shift=q[5]; p.left_shift=q[6]; p.output_multiplier=q[7];
  p.output_shift=q[8]; p.output_offset=q[9]; p.quantized_activation_min=q[10]; p.quantized_activation_max=q[11];
  tflite::reference_integer_ops::AddElementwise(n,p,a,b,out);
}
void check_tflm_softmax(int32_t m,int s,int diff,const int8_t *a,int8_t *b,int n) {
  tflite::SoftmaxParams p = {}; p.input_multiplier=m; p.input_left_shift=s; p.diff_min=diff;
  tflite::RuntimeShape shape({1,n});
  tflite::reference_ops::Softmax(p,shape,a,shape,b);
}
}
