// Host definitions for unused RISC-V intrinsics; scalar NMSIS math is unchanged.
#ifndef CONV_NPU_HOST_COMPAT_H
#define CONV_NPU_HOST_COMPAT_H
#include <stdint.h>
#include <string.h>
#define __GNUC_PYTHON__ 1
#define __ASM __asm__
#define __RESTRICT __restrict
static inline int32_t __SSAT(int32_t x,uint32_t bits) {
    int32_t max=(int32_t)((1u<<(bits-1u))-1u),min=-max-1;
    return x>max?max:x<min?min:x;
}
static inline uint32_t __LW(const void *p) {uint32_t x;memcpy(&x,p,4);return x;}
static inline void __SW(void *p,uint32_t x) {memcpy(p,&x,4);}
#endif
