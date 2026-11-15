// SPDX-License-Identifier: Apache-2.0
// Oracle calls the repository's actual TFLite utility implementations.
#include <cstdint>
#include <iostream>
#include "tensorflow/lite/kernels/internal/quantization_util.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/padding.h"

int main() {
    char kind;
    unsigned quantized_channels=0, activation_ranges=0, geometry_checks=0;
    while (std::cin >> kind) {
        if (kind=='Q') {
            float input_scale,weight_scale,output_scale;
            int32_t expected_multiplier,multiplier; int expected_shift,shift;
            std::cin >> input_scale >> weight_scale >> output_scale >> expected_multiplier >> expected_shift;
            tflite::QuantizeMultiplier(double(input_scale)*double(weight_scale)/double(output_scale),&multiplier,&shift);
            if (multiplier!=expected_multiplier || shift!=expected_shift) return 11;
            ++quantized_channels;
        } else if (kind=='A') {
            int activation,zero_point,expected_min,expected_max,actual_min,actual_max;
            float scale;
            std::cin >> activation >> scale >> zero_point >> expected_min >> expected_max;
            TfLiteTensor output={}; TfLiteContext context={};
            output.type=kTfLiteInt8;output.params.scale=scale;output.params.zero_point=zero_point;
            if (tflite::CalculateActivationRangeQuantized(&context,static_cast<TfLiteFusedActivation>(activation),
                    &output,&actual_min,&actual_max)!=kTfLiteOk) return 12;
            if (actual_min!=expected_min || actual_max!=expected_max) return 13;
            ++activation_ranges;
        } else if (kind=='P') {
            int mode,ih,iw,kh,kw,sh,sw,dh,dw,oh,ow,top,left,bottom,right,actual_h,actual_w;
            std::cin >> mode >> ih >> iw >> kh >> kw >> sh >> sw >> dh >> dw >> oh >> ow >> top >> left >> bottom >> right;
            auto pad=tflite::ComputePaddingHeightWidth(sh,sw,dh,dw,ih,iw,kh,kw,
                static_cast<TfLitePadding>(mode),&actual_h,&actual_w);
            if (actual_h!=oh || actual_w!=ow || pad.height!=top || pad.width!=left ||
                pad.height+pad.height_offset!=bottom || pad.width+pad.width_offset!=right) return 14;
            ++geometry_checks;
        } else return 15;
        if (!std::cin) return 16;
    }
    std::cout << "MODEL_METADATA_ORACLE_PASS channels=" << quantized_channels
              << " activation_ranges=" << activation_ranges << " geometries=" << geometry_checks << '\n';
}
