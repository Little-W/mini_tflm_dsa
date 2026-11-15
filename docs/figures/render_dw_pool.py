#!/usr/bin/env python3
"""Render DW architecture and measured PE comparisons with matplotlib."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE.parent / 'dw_pool_measurements_20261115.json').read_text())
FONT = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
if FONT.exists():
    font_manager.fontManager.addfont(str(FONT))
    plt.rcParams['font.family'] = font_manager.FontProperties(fname=FONT).get_name()
plt.rcParams.update({'font.size': 11, 'axes.unicode_minus': False,
                     'svg.fonttype': 'path', 'savefig.facecolor': '#f7f9fc'})
NAVY, BLUE, TEAL, INK, GRAY = '#142c49', '#2463a5', '#167a73', '#1c3148', '#64748b'


def box(ax, x, y, w, h, title, detail='', color=BLUE, fill='white'):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.012,rounding_size=0.018',
                               linewidth=1.4, edgecolor=color, facecolor=fill))
    ax.text(x+w/2, y+h*0.69 if detail else y+h/2, title, color=color,
            ha='center', va='center', weight='bold', fontsize=12)
    if detail:
        ax.text(x+w/2, y+h*0.30, detail, color=INK, ha='center', va='center', fontsize=10.2,
                linespacing=1.45)


def arrow(ax, a, b, both=False, color=GRAY):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle='<->' if both else '-|>',
                                mutation_scale=13, linewidth=1.6, color=color))


def save(fig, name):
    fig.savefig(HERE / (name+'.png'), dpi=180, bbox_inches='tight', pad_inches=0.2)
    svg = HERE / (name+'.svg')
    fig.savefig(svg, bbox_inches='tight', pad_inches=0.2)
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    plt.close(fig)


fig, ax = plt.subplots(figsize=(11.5, 9.5), facecolor='#f7f9fc')
ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis('off')
ax.text(.02, .97, 'DW、池化与向量运算引擎', fontsize=22, weight='bold', color=NAVY)
ax.text(.02, .935, '默认 8 PE · 可选 4 PE · 复用现有 DMA 与 im2col', color=GRAY, fontsize=12)
box(ax, .31, .84, .38, .065, 'NMSIS / C 驱动')
box(ax, .31, .735, .38, .065, 'AXI-Lite 配置与完成状态')
arrow(ax, (.5,.84), (.5,.80), both=True)
ax.text(.53,.82,'MMIO',color=GRAY,fontsize=9,va='center')

ax.add_patch(FancyBboxPatch((.035,.355),.59,.335,boxstyle='round,pad=0.012,rounding_size=0.018',
                           facecolor='#eaf2fb',edgecolor=BLUE,linewidth=1.6))
ax.text(.33,.661,'dw_pool_engine',ha='center',weight='bold',fontsize=15,color=BLUE)
box(ax,.065,.565,.53,.065,'任务控制与数据暂存','通道 / 空间位置 / 核位置 · 权重与参数复用')
for lane in range(8):
    x=.067+lane*.066
    ax.add_patch(FancyBboxPatch((x,.463),.055,.065,
                 boxstyle='round,pad=0.004,rounding_size=0.009',facecolor='white',edgecolor=TEAL))
    ax.text(x+.0275,.495,f'PE{lane}',ha='center',va='center',color=TEAL,fontsize=10)
ax.text(.33,.44,'每个 PE：s16 × s16 → s32 · sum / max / min',ha='center',fontsize=10,color=INK)
box(ax,.065,.365,.53,.05,'共享量化、平均值除法与输出字节选择',color=TEAL)
arrow(ax,(.33,.565),(.33,.534),color=BLUE)
arrow(ax,(.33,.431),(.33,.417),color=BLUE)
box(ax,.70,.455,.26,.13,'现有 Conv / GEMM','IA / kernel / 量化\n结果写回客户端',color=GRAY)
arrow(ax,(.40,.735),(.33,.69),color=BLUE)
arrow(ax,(.64,.735),(.83,.585),color=GRAY)

box(ax,.16,.18,.68,.095,'共享 DMA：仲裁、im2col、输入缓存与 AXI 读写',
    '原始输入缓存 1 KiB · 精确读取范围 · 32 位 AXI',color=NAVY,fill='#eef2f7')
arrow(ax,(.33,.343),(.33,.28),both=True,color=BLUE)
ax.text(.05,.305,'窗口 / 线性读取\n输入返回 / 结果写回',fontsize=9.7,color=BLUE,va='center')
arrow(ax,(.83,.455),(.73,.281),both=True,color=GRAY)
box(ax,.32,.04,.36,.065,'外部存储器 / AXI RAM',color=NAVY)
arrow(ax,(.50,.18),(.50,.105),both=True,color=NAVY)
ax.text(.54,.14,'数据与响应',fontsize=10,color=GRAY,va='center')
save(fig,'dw_pool_architecture')

fig, (a,b) = plt.subplots(1,2,figsize=(12.8,5.7),facecolor='#f7f9fc',gridspec_kw={'width_ratios':[1.25,1]})
fig.suptitle('PE 数量：完整任务周期与计算逻辑规模',x=.07,ha='left',fontsize=20,weight='bold',color=NAVY)
fig.text(.07,.88,'TILE=16，AXI=32 位；周期来自实际 RTL，逻辑规模来自独立 PE 阵列综合。',color=GRAY,fontsize=11)
pes=[x['pe_count'] for x in DATA['performance']]
series=[('perf_dot_s8','s8 点积，1024 元素',BLUE),('perf_dw_c32','DW 8×8×32，3×3',TEAL),
        ('perf_hadamard_s16','s16 Hadamard，1024 元素','#b66a20')]
for key,label,color in series:
    vals=[next(c['cycles'] for c in run['cases'] if c['name']==key) for run in DATA['performance']]
    a.plot(pes,[v/vals[0] for v in vals],marker='o',linewidth=2.2,label=label,color=color)
a.axvspan(4,8,color=BLUE,alpha=.07)
a.set_xscale('log',base=2);a.set_xticks(pes,labels=pes)
a.set_xlabel('PE 数量');a.set_ylabel('任务周期 / 1 PE 任务周期');a.set_ylim(.55,1.04)
a.set_title('完整任务周期',loc='left',pad=13,color=INK,fontsize=13,weight='bold')
a.legend(loc='lower left',fontsize=9,frameon=False)
a.grid(axis='y',color='#dce3ec',linewidth=.7);a.set_axisbelow(True)
cells=[r['generic_cell_count'] for r in DATA['pe_synthesis']]
bars=b.bar(range(len(pes)),cells,color=[GRAY,GRAY,TEAL,BLUE,GRAY],width=.65)
for bar,v in zip(bars,cells):
    b.text(bar.get_x()+bar.get_width()/2,v+650,f'{v:,}',ha='center',color=INK,fontsize=9.5)
b.set_xticks(range(len(pes)),labels=pes);b.set_xlabel('PE 数量');b.set_ylabel('通用逻辑单元数量')
b.set_ylim(0,40500);b.set_title('独立 PE 阵列，Yosys 0.71',loc='left',pad=13,color=INK,fontsize=13,weight='bold')
b.grid(axis='y',color='#dce3ec',linewidth=.7);b.set_axisbelow(True)
for axis in (a,b):
    axis.set_facecolor('#f7f9fc')
    axis.spines[['top','right']].set_visible(False)
    axis.spines[['left','bottom']].set_color('#aab7c8')
fig.text(.07,.025,'4 PE → 8 PE：点积总周期减少 7.57%；DW 总周期减少 1.06%；PE 执行周期减半。',color=INK,fontsize=11)
fig.subplots_adjust(top=.77,bottom=.19,left=.08,right=.98,wspace=.31)
save(fig,'dw_pool_pe_comparison')
print('Rendered architecture and PE comparison as PNG and SVG.')
