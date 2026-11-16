/* SPDX-License-Identifier: Apache-2.0 */
#define main vector_engine_regression_main
#include "../vector_engine/main.cpp"
#undef main
#include "../vector_engine/softmax_tests.h"

int main(int argc,char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Sim simulation;
    softmax_functional(simulation);
    softmax_invalid(simulation);
    if(argc>1)softmax_replay(simulation,argv[1]);
    std::printf("SOFTMAX_DMA_PASS cases=%u outputs=%llu\n",softmax_cases,
        static_cast<unsigned long long>(softmax_outputs));
    return 0;
  } catch(const std::exception& e) {std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
