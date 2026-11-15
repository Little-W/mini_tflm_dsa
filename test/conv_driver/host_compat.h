#ifndef CONV_HOST_COMPAT_H
#define CONV_HOST_COMPAT_H
#include <stdint.h>
#include <string.h>
#define __GNUC_PYTHON__ 1
#define __ASM __asm__
#define __RESTRICT __restrict
static inline int32_t __SSAT(int32_t x, uint32_t bits) {
    int32_t max = (int32_t)((1u << (bits - 1u)) - 1u);
    int32_t min = -max - 1;
    return x > max ? max : x < min ? min : x;
}
static inline uint32_t __LW(const void *p) { uint32_t v; memcpy(&v,p,4); return v; }
static inline void __SW(void *p, uint32_t v) { memcpy(p,&v,4); }
#endif
