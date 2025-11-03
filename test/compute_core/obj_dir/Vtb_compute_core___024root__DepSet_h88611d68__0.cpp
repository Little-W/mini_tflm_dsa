// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core__Syms.h"
#include "Vtb_compute_core___024root.h"

extern const VlWide<15>/*479:0*/ Vtb_compute_core__ConstPool__CONST_h74c5fa06_0;
extern const VlWide<14>/*447:0*/ Vtb_compute_core__ConstPool__CONST_hf10fc003_0;
extern const VlWide<16>/*511:0*/ Vtb_compute_core__ConstPool__CONST_hed238025_0;
extern const VlWide<15>/*479:0*/ Vtb_compute_core__ConstPool__CONST_h4bc113d1_0;

VL_INLINE_OPT VlCoroutine Vtb_compute_core___024root___eval_initial__TOP__Vtiming__0(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_initial__TOP__Vtiming__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_weight_tile__0__seg;
    __Vtask_tb_compute_core__DOT__load_weight_tile__0__seg = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c;
    __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8;
    __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32;
    __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k;
    __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j;
    __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_bias__1__seg;
    __Vtask_tb_compute_core__DOT__load_bias__1__seg = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c;
    __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c;
    __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg;
    __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k;
    __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16;
    __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0;
    __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1;
    __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 = 0;
    IData/*31:0*/ __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r;
    __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r = 0;
    // Body
    VL_READMEM_N(true, 8, 64, 0, VL_CVT_PACK_STR_NW(15, Vtb_compute_core__ConstPool__CONST_h74c5fa06_0)
                 ,  &(vlSelfRef.tb_compute_core__DOT__weight_mem_raw)
                 , 0, ~0ULL);
    VL_READMEM_N(true, 16, 64, 0, VL_CVT_PACK_STR_NW(14, Vtb_compute_core__ConstPool__CONST_hf10fc003_0)
                 ,  &(vlSelfRef.tb_compute_core__DOT__ia_mem_raw)
                 , 0, ~0ULL);
    VL_READMEM_N(true, 32, 16, 0, VL_CVT_PACK_STR_NW(16, Vtb_compute_core__ConstPool__CONST_hed238025_0)
                 ,  &(vlSelfRef.tb_compute_core__DOT__exp_mem)
                 , 0, ~0ULL);
    VL_READMEM_N(true, 32, 4, 0, VL_CVT_PACK_STR_NW(15, Vtb_compute_core__ConstPool__CONST_h4bc113d1_0)
                 ,  &(vlSelfRef.tb_compute_core__DOT__bias_mem)
                 , 0, ~0ULL);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [1U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [2U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [3U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[1U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [1U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [4U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[1U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [1U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [5U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[1U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [1U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [6U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[1U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [1U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [7U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[2U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [2U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [8U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[2U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [2U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [9U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[2U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [2U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0xaU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[2U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [2U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0xbU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[3U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [3U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0xcU]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[3U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [3U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0xdU] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[3U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [3U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0xeU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[3U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [3U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0xfU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[4U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [4U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x10U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[4U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [4U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x11U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[4U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [4U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x12U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[4U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [4U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x13U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[5U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [5U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x14U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[5U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [5U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x15U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[5U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [5U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x16U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[5U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [5U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x17U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[6U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [6U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x18U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[6U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [6U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x19U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[6U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [6U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x1aU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[6U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [6U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x1bU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[7U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [7U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x1cU]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[7U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [7U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x1dU] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[7U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [7U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x1eU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[7U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [7U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x1fU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[8U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [8U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x20U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[8U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [8U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x21U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[8U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [8U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x22U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[8U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [8U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x23U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[9U] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [9U]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x24U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[9U] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [9U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x25U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[9U] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [9U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x26U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[9U] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [9U]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                     [0x27U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xaU] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xaU]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x28U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xaU] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xaU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x29U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xaU] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xaU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x2aU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xaU] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xaU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x2bU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xbU] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xbU]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x2cU]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xbU] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xbU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x2dU] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xbU] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xbU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x2eU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xbU] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xbU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x2fU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xcU] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xcU]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x30U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xcU] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xcU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x31U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xcU] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xcU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x32U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xcU] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xcU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x33U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xdU] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xdU]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x34U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xdU] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xdU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x35U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xdU] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xdU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x36U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xdU] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xdU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x37U] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xeU] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xeU]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x38U]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xeU] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xeU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x39U] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xeU] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xeU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x3aU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xeU] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xeU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x3bU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xfU] 
        = ((0xffffff00U & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xfU]) | vlSelfRef.tb_compute_core__DOT__weight_mem_raw
           [0x3cU]);
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xfU] 
        = ((0xffff00ffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xfU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x3dU] << 8U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xfU] 
        = ((0xff00ffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xfU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x3eU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__weight_mem[0xfU] 
        = ((0xffffffU & vlSelfRef.tb_compute_core__DOT__weight_mem
            [0xfU]) | (vlSelfRef.tb_compute_core__DOT__weight_mem_raw
                       [0x3fU] << 0x18U));
    vlSelfRef.tb_compute_core__DOT__unnamedblk2__DOT__i = 0x10U;
    vlSelfRef.tb_compute_core__DOT__ia_mem[0U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [0U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [0U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [0U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [1U] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[1U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [1U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [2U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[1U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [1U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [3U] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[2U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [2U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [4U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[2U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [2U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [5U] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[3U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [3U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [6U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[3U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [3U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [7U] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[4U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [4U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [8U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[4U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [4U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [9U] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[5U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [5U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [0xaU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[5U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [5U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [0xbU] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[6U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [6U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [0xcU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[6U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [6U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [0xdU] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[7U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [7U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [0xeU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[7U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [7U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [0xfU] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[8U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [8U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [0x10U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[8U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [8U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [0x11U] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[9U] = ((0xffff0000U 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [9U]) 
                                                  | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                  [0x12U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[9U] = ((0xffffU 
                                                   & vlSelfRef.tb_compute_core__DOT__ia_mem
                                                   [9U]) 
                                                  | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                                                     [0x13U] 
                                                     << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xaU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xaU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x14U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xaU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xaU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                     [0x15U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xbU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xbU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x16U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xbU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xbU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                     [0x17U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xcU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xcU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x18U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xcU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xcU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                     [0x19U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xdU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xdU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x1aU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xdU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xdU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                     [0x1bU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xeU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xeU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x1cU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xeU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xeU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                     [0x1dU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xfU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xfU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x1eU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0xfU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0xfU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                     [0x1fU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x10U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x10U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x20U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x10U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x10U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x21U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x11U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x11U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x22U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x11U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x11U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x23U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x12U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x12U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x24U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x12U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x12U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x25U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x13U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x13U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x26U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x13U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x13U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x27U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x14U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x14U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x28U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x14U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x14U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x29U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x15U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x15U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x2aU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x15U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x15U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x2bU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x16U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x16U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x2cU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x16U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x16U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x2dU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x17U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x17U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x2eU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x17U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x17U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x2fU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x18U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x18U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x30U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x18U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x18U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x31U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x19U] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x19U]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x32U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x19U] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x19U]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x33U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1aU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1aU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x34U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1aU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1aU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x35U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1bU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1bU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x36U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1bU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1bU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x37U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1cU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1cU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x38U]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1cU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1cU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x39U] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1dU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1dU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x3aU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1dU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1dU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x3bU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1eU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1eU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x3cU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1eU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1eU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x3dU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1fU] = 
        ((0xffff0000U & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1fU]) | vlSelfRef.tb_compute_core__DOT__ia_mem_raw
         [0x3eU]);
    vlSelfRef.tb_compute_core__DOT__ia_mem[0x1fU] = 
        ((0xffffU & vlSelfRef.tb_compute_core__DOT__ia_mem
          [0x1fU]) | (vlSelfRef.tb_compute_core__DOT__ia_mem_raw
                      [0x3fU] << 0x10U));
    vlSelfRef.tb_compute_core__DOT__unnamedblk3__DOT__i = 0x20U;
    co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_compute_core.tb_if.cb)", 
                                                         "tb_compute_core.sv", 
                                                         110);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_compute_core.tb_if.cb)", 
                                                         "tb_compute_core.sv", 
                                                         110);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_compute_core.tb_if.cb)", 
                                                         "tb_compute_core.sv", 
                                                         110);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_compute_core.tb_if.cb)", 
                                                         "tb_compute_core.sv", 
                                                         110);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_compute_core.tb_if.cb)", 
                                                         "tb_compute_core.sv", 
                                                         110);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg = 0U;
    while (VL_LTS_III(32, vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg, vlSelfRef.tb_compute_core__DOT__NUM_SEG)) {
        if (VL_UNLIKELY(((0U != vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg)))) {
            VL_WRITEF_NX("[TB] Wait partial_sum_calc_over before next weight seg=%0d\n",0,
                         32,vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg);
            while ((1U & (~ (IData)(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over)))) {
                co_await vlSelfRef.__VtrigSched_h76832c6c__0.trigger(1U, 
                                                                     nullptr, 
                                                                     "@( tb_compute_core.__Vcellout__u_dut__partial_sum_calc_over)", 
                                                                     "tb_compute_core.sv", 
                                                                     117);
                vlSelfRef.__Vm_traceActivity[2U] = 1U;
            }
            co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_compute_core.tb_if.cb)", 
                                                                 "tb_compute_core.sv", 
                                                                 118);
            vlSelfRef.__Vm_traceActivity[2U] = 1U;
        }
        VL_WRITEF_NX("[TB] Loading weight tile seg=%0d\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg);
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__seg 
            = vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c = 0;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 = 0;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 = 0;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k = 0;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 0;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__store_weight_req = 1U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c = 0U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
            = VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__load_weight_tile__0__seg, 2U);
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
            = vlSelfRef.tb_compute_core__DOT__weight_mem
            [(0xfU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
                      >> 2U))];
        vlSelfRef.tb_compute_core__DOT__tile_buf[0U][0U] 
            = (0xffU & __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32);
        vlSelfRef.tb_compute_core__DOT__tile_buf[1U][0U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 8U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[2U][0U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 0x10U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[3U][0U] 
            = (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
               >> 0x18U);
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c = 1U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
            = (VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__load_weight_tile__0__seg, 2U) 
               + vlSelfRef.tb_compute_core__DOT__NUM_K);
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
            = vlSelfRef.tb_compute_core__DOT__weight_mem
            [(0xfU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
                      >> 2U))];
        vlSelfRef.tb_compute_core__DOT__tile_buf[0U][1U] 
            = (0xffU & __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32);
        vlSelfRef.tb_compute_core__DOT__tile_buf[1U][1U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 8U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[2U][1U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 0x10U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[3U][1U] 
            = (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
               >> 0x18U);
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c = 2U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
            = (VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__load_weight_tile__0__seg, 2U) 
               + VL_SHIFTL_III(32,32,32, vlSelfRef.tb_compute_core__DOT__NUM_K, 1U));
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
            = vlSelfRef.tb_compute_core__DOT__weight_mem
            [(0xfU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
                      >> 2U))];
        vlSelfRef.tb_compute_core__DOT__tile_buf[0U][2U] 
            = (0xffU & __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32);
        vlSelfRef.tb_compute_core__DOT__tile_buf[1U][2U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 8U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[2U][2U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 0x10U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[3U][2U] 
            = (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
               >> 0x18U);
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c = 3U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
            = (VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__load_weight_tile__0__seg, 2U) 
               + ((IData)(3U) * vlSelfRef.tb_compute_core__DOT__NUM_K));
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
            = vlSelfRef.tb_compute_core__DOT__weight_mem
            [(0xfU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__base_idx8 
                      >> 2U))];
        vlSelfRef.tb_compute_core__DOT__tile_buf[0U][3U] 
            = (0xffU & __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32);
        vlSelfRef.tb_compute_core__DOT__tile_buf[1U][3U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 8U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[2U][3U] 
            = (0xffU & (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
                        >> 0x10U));
        vlSelfRef.tb_compute_core__DOT__tile_buf[3U][3U] 
            = (__Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__unnamedblk10__DOT__w32 
               >> 0x18U);
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk9__DOT__c = 4U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k = 3U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 0U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[0U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [3U][0U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 1U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[1U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [3U][1U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 2U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[2U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [3U][2U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 3U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[3U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [3U][3U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 4U;
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             200);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k = 2U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 0U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[0U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [2U][0U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 1U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[1U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [2U][1U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 2U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[2U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [2U][2U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 3U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[3U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [2U][3U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 4U;
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             200);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k = 1U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 0U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[0U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [1U][0U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 1U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[1U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [1U][1U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 2U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[2U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [1U][2U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 3U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[3U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [1U][3U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 4U;
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             200);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k = 0U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 0U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[0U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [0U][0U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 1U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[1U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [0U][1U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 2U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[2U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [0U][2U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 3U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in[3U] 
            = vlSelfRef.tb_compute_core__DOT__tile_buf
            [0U][3U];
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__unnamedblk12__DOT__j = 4U;
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             200);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__load_weight_tile__0__unnamedblk11__DOT__k = 0xffffffffU;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__store_weight_req = 0U;
        __Vtask_tb_compute_core__DOT__load_bias__1__seg 
            = vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg;
        __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c = 0;
        __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c = 0;
        if ((0U == __Vtask_tb_compute_core__DOT__load_bias__1__seg)) {
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c = 0U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[0U] 
                = vlSelfRef.tb_compute_core__DOT__bias_mem
                [0U];
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c = 1U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[1U] 
                = vlSelfRef.tb_compute_core__DOT__bias_mem
                [1U];
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c = 2U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[2U] 
                = vlSelfRef.tb_compute_core__DOT__bias_mem
                [2U];
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c = 3U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[3U] 
                = vlSelfRef.tb_compute_core__DOT__bias_mem
                [3U];
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk7__DOT__c = 4U;
        } else {
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c = 0U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[0U] = 0U;
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c = 1U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[1U] = 0U;
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c = 2U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[2U] = 0U;
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c = 3U;
            vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in[3U] = 0U;
            __Vtask_tb_compute_core__DOT__load_bias__1__unnamedblk8__DOT__c = 4U;
        }
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             129);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        VL_WRITEF_NX("[TB] Streaming IA tile seg=%0d\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg);
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg 
            = vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k = 0;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 = 0;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 = 0;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 = 0;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r = 0;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_row_valid = 1U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_is_init_data 
            = (0U == __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_calc_done 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg 
               == (vlSelfRef.tb_compute_core__DOT__NUM_SEG 
                   - (IData)(1U)));
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k = 0U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
            = VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg, 2U);
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
                       >> 1U))];
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (((IData)(2U) + __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16) 
                       >> 1U))];
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[0U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[1U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
               >> 0x10U);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[2U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[3U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
               >> 0x10U);
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             221);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k = 1U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
            = (VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg, 2U) 
               + vlSelfRef.tb_compute_core__DOT__NUM_K);
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
                       >> 1U))];
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (((IData)(2U) + __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16) 
                       >> 1U))];
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[0U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[1U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
               >> 0x10U);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[2U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[3U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
               >> 0x10U);
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             221);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k = 2U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
            = (VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg, 2U) 
               + VL_SHIFTL_III(32,32,32, vlSelfRef.tb_compute_core__DOT__NUM_K, 1U));
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
                       >> 1U))];
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (((IData)(2U) + __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16) 
                       >> 1U))];
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[0U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[1U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
               >> 0x10U);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[2U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[3U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
               >> 0x10U);
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             221);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k = 3U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
            = (VL_SHIFTL_III(32,32,32, __Vtask_tb_compute_core__DOT__stream_ia_tile__2__seg, 2U) 
               + ((IData)(3U) * vlSelfRef.tb_compute_core__DOT__NUM_K));
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16 
                       >> 1U))];
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
            = vlSelfRef.tb_compute_core__DOT__ia_mem
            [(0x1fU & (((IData)(2U) + __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__base16) 
                       >> 1U))];
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[0U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[1U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p0 
               >> 0x10U);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[2U] 
            = (0xffffU & __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1);
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[3U] 
            = (__Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__unnamedblk14__DOT__p1 
               >> 0x10U);
        co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_compute_core.tb_if.cb)", 
                                                             "tb_compute_core.sv", 
                                                             221);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk13__DOT__k = 4U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_row_valid = 0U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_is_init_data = 0U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_calc_done = 0U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r = 0U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[0U] = 0U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r = 1U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[1U] = 0U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r = 2U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[2U] = 0U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r = 3U;
        vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in[3U] = 0U;
        __Vtask_tb_compute_core__DOT__stream_ia_tile__2__unnamedblk15__DOT__r = 4U;
        vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg 
            = ((IData)(1U) + vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg);
    }
    VL_WRITEF_NX("[TB] Waiting for tile_calc_over...\n",0);
    while ((1U & (~ (IData)(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over)))) {
        co_await vlSelfRef.__VtrigSched_hf86aeebc__0.trigger(1U, 
                                                             nullptr, 
                                                             "@( tb_compute_core.__Vcellout__u_dut__tile_calc_over)", 
                                                             "tb_compute_core.sv", 
                                                             138);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
    }
    VL_WRITEF_NX("[TB] tile_calc_over detected\n",0);
    co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_compute_core.tb_if.cb)", 
                                                         "tb_compute_core.sv", 
                                                         140);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    co_await vlSelfRef.__VtrigSched_h08f02b2e__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_compute_core.tb_if.cb)", 
                                                         "tb_compute_core.sv", 
                                                         140);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    if (VL_UNLIKELY(((4U > vlSelfRef.tb_compute_core__DOT__out_rows)))) {
        VL_WRITEF_NX("ERROR: output rows=%0d < expected=4\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_rows);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__r = 0U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 0U;
    vlSelfRef.tb_compute_core__DOT__idx = 0U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=0 c=0\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 1U;
    vlSelfRef.tb_compute_core__DOT__idx = 1U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=0 c=1\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 2U;
    vlSelfRef.tb_compute_core__DOT__idx = 2U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=0 c=2\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 3U;
    vlSelfRef.tb_compute_core__DOT__idx = 3U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=0 c=3\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 4U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__r = 1U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 0U;
    vlSelfRef.tb_compute_core__DOT__idx = 4U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=1 c=0\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 1U;
    vlSelfRef.tb_compute_core__DOT__idx = 5U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=1 c=1\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 2U;
    vlSelfRef.tb_compute_core__DOT__idx = 6U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=1 c=2\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 3U;
    vlSelfRef.tb_compute_core__DOT__idx = 7U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=1 c=3\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 4U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__r = 2U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 0U;
    vlSelfRef.tb_compute_core__DOT__idx = 8U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=2 c=0\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 1U;
    vlSelfRef.tb_compute_core__DOT__idx = 9U;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=2 c=1\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 2U;
    vlSelfRef.tb_compute_core__DOT__idx = 0xaU;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=2 c=2\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 3U;
    vlSelfRef.tb_compute_core__DOT__idx = 0xbU;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=2 c=3\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 4U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__r = 3U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 0U;
    vlSelfRef.tb_compute_core__DOT__idx = 0xcU;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=3 c=0\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 1U;
    vlSelfRef.tb_compute_core__DOT__idx = 0xdU;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=3 c=1\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 2U;
    vlSelfRef.tb_compute_core__DOT__idx = 0xeU;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=3 c=2\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 3U;
    vlSelfRef.tb_compute_core__DOT__idx = 0xfU;
    if (VL_UNLIKELY(((vlSelfRef.tb_compute_core__DOT__out_buf
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)] 
                      != vlSelfRef.tb_compute_core__DOT__exp_mem
                      [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)])))) {
        VL_WRITEF_NX("MISMATCH r=3 c=3\n  got=%0d (0x%08x)\n  exp=%0d (0x%08x)\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__out_buf
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)],
                     32,vlSelfRef.tb_compute_core__DOT__exp_mem
                     [(0xfU & vlSelfRef.tb_compute_core__DOT__idx)]);
        vlSelfRef.tb_compute_core__DOT__errors = ((IData)(1U) 
                                                  + vlSelfRef.tb_compute_core__DOT__errors);
    }
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 4U;
    vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__r = 4U;
    if ((0U == vlSelfRef.tb_compute_core__DOT__errors)) {
        VL_WRITEF_NX("\033[0;32mPASS: compute_core 4x16 * 16x4 matched expected\033[0m\n",0);
    } else {
        VL_WRITEF_NX("\033[0;31mFAIL: %0d mismatches\033[0m\n",0,
                     32,vlSelfRef.tb_compute_core__DOT__errors);
    }
    co_await vlSelfRef.__VdlySched.delay(0x4e20ULL, 
                                         nullptr, "tb_compute_core.sv", 
                                         161);
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    VL_FINISH_MT("tb_compute_core.sv", 162, "");
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
}

VL_INLINE_OPT VlCoroutine Vtb_compute_core___024root___eval_initial__TOP__Vtiming__1(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_initial__TOP__Vtiming__1\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    while (VL_LIKELY(!vlSymsp->_vm_contextp__->gotFinish())) {
        co_await vlSelfRef.__VdlySched.delay(0x1388ULL, 
                                             nullptr, 
                                             "tb_compute_core.sv", 
                                             15);
        vlSelfRef.__VdlyVal__tb_compute_core__DOT__clk__v0 
            = (1U & (~ (IData)(vlSelfRef.tb_compute_core__DOT__clk)));
        vlSelfRef.__VdlySet__tb_compute_core__DOT__clk__v0 = 1U;
    }
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__act(Vtb_compute_core___024root* vlSelf);
#endif  // VL_DEBUG

void Vtb_compute_core___024root___eval_triggers__act(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_triggers__act\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.__VactTriggered.setBit(0U, ((IData)(vlSelfRef.tb_compute_core__DOT__clk) 
                                          & (~ (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__clk__0))));
    vlSelfRef.__VactTriggered.setBit(1U, vlSelfRef.__VdlySched.awaitingCurrentTime());
    vlSelfRef.__VactTriggered.setBit(2U, vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__bias_in__0.neq(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in));
    vlSelfRef.__VactTriggered.setBit(3U, ((IData)(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_is_init_data) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_is_init_data__0)));
    vlSelfRef.__VactTriggered.setBit(4U, ((IData)(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_calc_done) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_calc_done__0)));
    vlSelfRef.__VactTriggered.setBit(5U, ((IData)(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_row_valid) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_row_valid__0)));
    vlSelfRef.__VactTriggered.setBit(6U, vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_vec_in__0.neq(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in));
    vlSelfRef.__VactTriggered.setBit(7U, vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__weight_in__0.neq(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in));
    vlSelfRef.__VactTriggered.setBit(8U, ((IData)(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__store_weight_req) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__store_weight_req__0)));
    vlSelfRef.__VactTriggered.setBit(9U, vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb.isFired());
    vlSelfRef.__VactTriggered.setBit(0xaU, ((IData)(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over) 
                                            != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over__0)));
    vlSelfRef.__VactTriggered.setBit(0xbU, ((IData)(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over) 
                                            != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over__0)));
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__clk__0 
        = vlSelfRef.tb_compute_core__DOT__clk;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__bias_in__0.assign(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in);
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_is_init_data__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_is_init_data;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_calc_done__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_calc_done;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_row_valid__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_row_valid;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_vec_in__0.assign(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in);
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__weight_in__0.assign(vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in);
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__store_weight_req__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__store_weight_req;
    vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb.clearFired();
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over__0 
        = vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over__0 
        = vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over;
    if (VL_UNLIKELY(((1U & (~ (IData)(vlSelfRef.__VactDidInit)))))) {
        vlSelfRef.__VactDidInit = 1U;
        vlSelfRef.__VactTriggered.setBit(2U, 1U);
        vlSelfRef.__VactTriggered.setBit(3U, 1U);
        vlSelfRef.__VactTriggered.setBit(4U, 1U);
        vlSelfRef.__VactTriggered.setBit(5U, 1U);
        vlSelfRef.__VactTriggered.setBit(6U, 1U);
        vlSelfRef.__VactTriggered.setBit(7U, 1U);
        vlSelfRef.__VactTriggered.setBit(8U, 1U);
        vlSelfRef.__VactTriggered.setBit(0xaU, 1U);
        vlSelfRef.__VactTriggered.setBit(0xbU, 1U);
    }
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vtb_compute_core___024root___dump_triggers__act(vlSelf);
    }
#endif
}

void Vtb_compute_core___024root___nba_sequent__TOP__0(Vtb_compute_core___024root* vlSelf);
void Vtb_compute_core_tb_compute_core_if___nba_sequent__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core___024root___nba_sequent__TOP__1(Vtb_compute_core___024root* vlSelf);

void Vtb_compute_core___024root___eval_nba(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_nba\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        Vtb_compute_core___024root___nba_sequent__TOP__0(vlSelf);
        vlSelfRef.__Vm_traceActivity[3U] = 1U;
        Vtb_compute_core_tb_compute_core_if___nba_sequent__TOP__tb_compute_core__DOT__tb_if__0((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    }
    if ((2ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        Vtb_compute_core___024root___nba_sequent__TOP__1(vlSelf);
    }
}

VL_INLINE_OPT void Vtb_compute_core___024root___nba_sequent__TOP__0(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___nba_sequent__TOP__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT____Vlvbound_ha6504e14__0;
    tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT____Vlvbound_ha6504e14__0 = 0;
    CData/*1:0*/ __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr = 0;
    CData/*1:0*/ __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr = 0;
    CData/*1:0*/ __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr = 0;
    CData/*1:0*/ __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr = 0;
    CData/*1:0*/ __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__out_buf__v0;
    __VdlyVal__tb_compute_core__DOT__out_buf__v0 = 0;
    CData/*3:0*/ __VdlyDim0__tb_compute_core__DOT__out_buf__v0;
    __VdlyDim0__tb_compute_core__DOT__out_buf__v0 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__out_buf__v0;
    __VdlySet__tb_compute_core__DOT__out_buf__v0 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__out_buf__v1;
    __VdlyVal__tb_compute_core__DOT__out_buf__v1 = 0;
    CData/*3:0*/ __VdlyDim0__tb_compute_core__DOT__out_buf__v1;
    __VdlyDim0__tb_compute_core__DOT__out_buf__v1 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__out_buf__v2;
    __VdlyVal__tb_compute_core__DOT__out_buf__v2 = 0;
    CData/*3:0*/ __VdlyDim0__tb_compute_core__DOT__out_buf__v2;
    __VdlyDim0__tb_compute_core__DOT__out_buf__v2 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__out_buf__v3;
    __VdlyVal__tb_compute_core__DOT__out_buf__v3 = 0;
    CData/*3:0*/ __VdlyDim0__tb_compute_core__DOT__out_buf__v3;
    __VdlyDim0__tb_compute_core__DOT__out_buf__v3 = 0;
    SData/*15:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v0 = 0;
    SData/*15:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v1 = 0;
    SData/*15:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v0 = 0;
    SData/*15:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v1 = 0;
    SData/*15:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v2 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v0 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v1 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v2 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v3;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v3 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v0 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v1 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v2 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v3;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v3 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v0 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v1 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v2 = 0;
    CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v3;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v3 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0;
    IData/*31:0*/ __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*1:0*/ __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    CData/*0:0*/ __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0;
    // Body
    __VdlySet__tb_compute_core__DOT__out_buf__v0 = 0U;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0U;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0U;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0U;
    __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 0U;
    __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 0U;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__k = 2U;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__k = 3U;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__unnamedblk1__DOT__m = 4U;
    if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg) {
        vlSelfRef.tb_compute_core__DOT__unnamedblk1__DOT__c = 4U;
        __VdlyVal__tb_compute_core__DOT__out_buf__v0 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out
            [0U];
        __VdlyDim0__tb_compute_core__DOT__out_buf__v0 
            = (0xfU & VL_SHIFTL_III(4,32,32, vlSelfRef.tb_compute_core__DOT__out_rows, 2U));
        __VdlySet__tb_compute_core__DOT__out_buf__v0 = 1U;
        __VdlyVal__tb_compute_core__DOT__out_buf__v1 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out
            [1U];
        __VdlyDim0__tb_compute_core__DOT__out_buf__v1 
            = (0xfU & ((IData)(1U) + VL_SHIFTL_III(4,32,32, vlSelfRef.tb_compute_core__DOT__out_rows, 2U)));
        __VdlyVal__tb_compute_core__DOT__out_buf__v2 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out
            [2U];
        __VdlyDim0__tb_compute_core__DOT__out_buf__v2 
            = (0xfU & ((IData)(2U) + VL_SHIFTL_III(4,32,32, vlSelfRef.tb_compute_core__DOT__out_rows, 2U)));
        __VdlyVal__tb_compute_core__DOT__out_buf__v3 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out
            [3U];
        __VdlyDim0__tb_compute_core__DOT__out_buf__v3 
            = (0xfU & ((IData)(3U) + VL_SHIFTL_III(4,32,32, vlSelfRef.tb_compute_core__DOT__out_rows, 2U)));
        vlSelfRef.tb_compute_core__DOT__out_rows = 
            ((IData)(1U) + vlSelfRef.tb_compute_core__DOT__out_rows);
    }
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_calc_done;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v1 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
        [0U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v2 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
        [1U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v3 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
        [2U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_is_init_data;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v1 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
        [0U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v2 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
        [1U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v3 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
        [2U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_row_valid;
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v1 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
        [0U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v2 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
        [1U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v3 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
        [2U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v0 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in
        [2U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v1 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
        [0U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v0 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in
        [3U];
    tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT____Vlvbound_ha6504e14__0 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
        [0U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v1 
        = tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT____Vlvbound_ha6504e14__0;
    tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT____Vlvbound_ha6504e14__0 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
        [1U];
    __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v2 
        = tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT____Vlvbound_ha6504e14__0;
    if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
        [3U]) {
        if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
            [3U]) {
            if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg) {
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [0U];
                __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr;
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 1U;
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr 
                    = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr)));
            } else {
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr = 1U;
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [0U];
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 1U;
            }
        } else {
            vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum 
                = (0x1ffffffffULL & (VL_EXTENDS_QI(33,32, 
                                                   vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
                                                   [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr]) 
                                     + VL_EXTENDS_QI(33,32, 
                                                     vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                                     [0U])));
            __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                    ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                                      ? 0x80000000U
                                      : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)));
            __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr;
            __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 1U;
            __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr 
                = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr)));
        }
    }
    if (((~ vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
          [3U]) & (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_i_d))) {
        __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr = 0U;
    }
    if ((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
         [3U] & (~ (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_i_d)))) {
        __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr = 0U;
    } else if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg) {
        __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr 
            = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr)));
    }
    if (vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over) {
        __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr = 0U;
    }
    if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg) {
        if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg) {
            if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg) {
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [1U];
                __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr;
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 1U;
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr 
                    = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr)));
            } else {
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr = 1U;
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [1U];
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 1U;
            }
        } else {
            vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum 
                = (0x1ffffffffULL & (VL_EXTENDS_QI(33,32, 
                                                   vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
                                                   [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr]) 
                                     + VL_EXTENDS_QI(33,32, 
                                                     vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                                     [1U])));
            __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                    ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                                      ? 0x80000000U
                                      : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)));
            __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr;
            __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 1U;
            __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr 
                = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr)));
        }
    }
    if (((~ (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg)) 
         & (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_i_d))) {
        __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr = 0U;
    }
    if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg) {
        if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg) {
            if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg) {
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [2U];
                __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr;
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 1U;
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr 
                    = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr)));
            } else {
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr = 1U;
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [2U];
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 1U;
            }
        } else {
            vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum 
                = (0x1ffffffffULL & (VL_EXTENDS_QI(33,32, 
                                                   vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
                                                   [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr]) 
                                     + VL_EXTENDS_QI(33,32, 
                                                     vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                                     [2U])));
            __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                    ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                                      ? 0x80000000U
                                      : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)));
            __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr;
            __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 1U;
            __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr 
                = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr)));
        }
    }
    if (((~ (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg)) 
         & (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_i_d))) {
        __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr = 0U;
    }
    if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg) {
        if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg) {
            if (vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg) {
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [3U];
                __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr;
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0 = 1U;
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr 
                    = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr)));
            } else {
                __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr = 1U;
                __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1 
                    = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                    [3U];
                __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1 = 1U;
            }
        } else {
            vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum 
                = (0x1ffffffffULL & (VL_EXTENDS_QI(33,32, 
                                                   vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
                                                   [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr]) 
                                     + VL_EXTENDS_QI(33,32, 
                                                     vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                                     [3U])));
            __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                    ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)
                                      ? 0x80000000U
                                      : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum)));
            __VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2 
                = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr;
            __VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2 = 1U;
            __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr 
                = (3U & ((IData)(1U) + (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr)));
        }
    }
    if (((~ (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg)) 
         & (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_i_d))) {
        __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr = 0U;
    }
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over 
        = ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_chain_d) 
           & (~ (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg)));
    if (vlSymsp->TOP__tb_compute_core__DOT__tb_if.store_weight_req) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
            [0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
            [1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
            [2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
            [3U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [0U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [0U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [0U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [0U][3U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [1U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [1U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [1U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [1U][3U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [2U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [2U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [2U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
            [2U][3U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = 0U;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = 0U;
    } else {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
            [0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
            [1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
            [2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
            [3U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg 
            = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
            [0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
            [1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
            [2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg;
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [0U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [0U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [0U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [1U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [1U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [1U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [2U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [2U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [2U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [3U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [3U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
            [3U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [0U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [0U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [0U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [0U][3U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [1U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [1U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [1U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [1U][3U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [2U][0U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [2U][1U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [2U][2U];
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
            = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
            [2U][3U];
    }
    if (__VdlySet__tb_compute_core__DOT__out_buf__v0) {
        vlSelfRef.tb_compute_core__DOT__out_buf[__VdlyDim0__tb_compute_core__DOT__out_buf__v0] 
            = __VdlyVal__tb_compute_core__DOT__out_buf__v0;
        vlSelfRef.tb_compute_core__DOT__out_buf[__VdlyDim0__tb_compute_core__DOT__out_buf__v1] 
            = __VdlyVal__tb_compute_core__DOT__out_buf__v1;
        vlSelfRef.tb_compute_core__DOT__out_buf[__VdlyDim0__tb_compute_core__DOT__out_buf__v2] 
            = __VdlyVal__tb_compute_core__DOT__out_buf__v2;
        vlSelfRef.tb_compute_core__DOT__out_buf[__VdlyDim0__tb_compute_core__DOT__out_buf__v3] 
            = __VdlyVal__tb_compute_core__DOT__out_buf__v3;
    }
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr 
        = __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr;
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[0U] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    }
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr 
        = __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr 
        = __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr;
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[0U] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    }
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr 
        = __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr;
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[0U] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    }
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr 
        = __Vdly__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr;
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v0;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[0U] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v1;
    }
    if (__VdlySet__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2) {
        vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[__VdlyDim0__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2] 
            = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo__v2;
    }
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg[0U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v0;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg[1U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg__v1;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[0U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v0;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[1U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v1;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[2U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg__v2;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_i_d 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
        [3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_i_d 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
        [3U];
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over 
        = ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__calc_done_o_d) 
           & (~ (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg)));
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_i_d 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg;
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_i_d 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg;
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_i_d 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_chain_d 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__calc_done_o_d 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
        [3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[0U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v0;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[1U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v1;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[2U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v2;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[3U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift__v3;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
        [3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[0U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v0;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[1U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v1;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[2U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v2;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[3U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift__v3;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
        [3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[0U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v0;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[1U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v1;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[2U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v2;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[3U] 
        = __VdlyVal__tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift__v3;
}

void Vtb_compute_core_tb_compute_core_if___obs_sequent__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core_tb_compute_core_if* vlSelf);

void Vtb_compute_core___024root___eval_obs(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_obs\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___obs_sequent__TOP__tb_compute_core__DOT__tb_if__0((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    }
}

void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__1(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__2(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__3(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__4(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core___024root___react_sequent__TOP__0(Vtb_compute_core___024root* vlSelf);
void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__5(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core___024root___react_sequent__TOP__1(Vtb_compute_core___024root* vlSelf);
void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__6(Vtb_compute_core_tb_compute_core_if* vlSelf);
void Vtb_compute_core___024root___react_sequent__TOP__2(Vtb_compute_core___024root* vlSelf);

void Vtb_compute_core___024root___eval_react(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_react\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((9ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__0((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    }
    if ((0x11ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__1((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    }
    if ((0x21ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__2((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    }
    if ((0x101ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__3((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    }
    if ((5ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__4((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
        vlSelfRef.__Vm_traceActivity[4U] = 1U;
        Vtb_compute_core___024root___react_sequent__TOP__0(vlSelf);
    }
    if ((0x81ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__5((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
        vlSelfRef.__Vm_traceActivity[5U] = 1U;
        Vtb_compute_core___024root___react_sequent__TOP__1(vlSelf);
    }
    if ((0x41ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__6((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
        vlSelfRef.__Vm_traceActivity[6U] = 1U;
        Vtb_compute_core___024root___react_sequent__TOP__2(vlSelf);
    }
}

VL_INLINE_OPT void Vtb_compute_core___024root___react_sequent__TOP__0(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___react_sequent__TOP__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [0U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [1U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [2U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [3U];
}

VL_INLINE_OPT void Vtb_compute_core___024root___react_sequent__TOP__1(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___react_sequent__TOP__1\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [0U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [1U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [2U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [3U];
}

VL_INLINE_OPT void Vtb_compute_core___024root___react_sequent__TOP__2(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___react_sequent__TOP__2\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [1U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [2U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [3U];
}
