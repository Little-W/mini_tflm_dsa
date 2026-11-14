
## 1) 先把目标化到最简形式

你给的  
$p=\frac{x}{a},\quad l=\frac{y}{b},\quad B=p\,l\,z\,(2ab-(a+b)) + a(l-1)$

代入并化简得（这是非常关键的一步）：
$\boxed{
B(a,b)=2xyz-\frac{xyz}{a}-\frac{xyz}{b}-a+\frac{ay}{b}
}$

---

## 2) 施加约束 $ab=S$：降成一元函数

由 $b=\frac{S}{a}$ 代入上式：

$B(a)=B\!\left(a,\frac{S}{a}\right)
=2xyz-\frac{xyz}{a}-\frac{xyz}{S}a-a+\frac{y}{S}a^2$

$\boxed{
B(a)=2xyz-\frac{xyz}{a}-\Big(\frac{xyz}{S}+1\Big)a+\frac{y}{S}a^2
}$

可行域由 $a\le x$ 与 $b\le y\Rightarrow \frac{S}{a}\le y\Rightarrow a\ge \frac{S}{y}$ 给出：
$\boxed{
a\in\Big[\frac{S}{y},\ x\Big]
}$
（若 $\frac{S}{y}>x$，无可行解）

---

## 3) 极值点：导数为 0 得到三次方程

一阶导：
$B'(a)=\frac{xyz}{a^2}-\frac{xyz}{S}-1+\frac{2y}{S}a$

令 $B'(a)=0$，两边乘 $a^2S$ 得：
$xyzS-xyz\,a^2-Sa^2+2ya^3=0$

记 $X=xyz$，得到驻点满足的三次方程：
$\boxed{
2y\,a^3-(X+S)a^2+XS=0
}$

因此连续域的最优 $a^*$ 一定在以下有限集合里：

- 端点 $a=\frac{S}{y}$
- 端点 $a=x$
- 三次方程 $2y a^3-(X+S)a^2+XS=0$ 的实根中落在可行域内的那些

取其中使 $B(a)$ 最大的那个即为 $a^*$，然后
$\boxed{b^*=\frac{S}{a^*}}$

---

## 4) Cardano 闭式：把三次方程写成“最终求解公式”

把三次方程除以 $2y$：
$a^3 + A a^2 + C = 0$

其中
$\boxed{
A=-\frac{X+S}{2y},\qquad C=\frac{XS}{2y}
}$

做降次代换（去掉二次项）：
$a=t-\frac{A}{3}$

可得 **降次三次方程**（depressed cubic）：
$t^3 + p t + q = 0$

其中（由于原方程一次项系数为 0，这里会特别简洁）：
$\boxed{
p=-\frac{A^2}{3},\qquad q=\frac{2A^3}{27}+C
}$

判别式：
$\boxed{
\Delta=\Big(\frac{q}{2}\Big)^2+\Big(\frac{p}{3}\Big)^3
}$

- 若 $\Delta\ge 0$，唯一实根：
  $\boxed{
  t=\sqrt[3]{-\frac{q}{2}+\sqrt{\Delta}}+\sqrt[3]{-\frac{q}{2}-\sqrt{\Delta}}
  }$

- 若 $\Delta<0$，有三个实根：  
  $r=\sqrt{-\frac{p}{3}},\quad
  \phi=\arccos\!\Big(\frac{-q/2}{r^3}\Big)$  
  $\boxed{
  t_k=2r\cos\Big(\frac{\phi+2k\pi}{3}\Big),\ k=0,1,2
  }$

最后：
$\boxed{
a_k = t_k-\frac{A}{3}
}$

把所有落在 $\left[\frac{S}{y},\ x\right]$ 的 $a_k$ 与端点一起比较 $B(a)$，取最大者为 $a^*$。

---

## 5) 代码（无遍历：只解三次方程 + 比较有限候选点）

下面代码实现上述“最终公式”，并用密集网格验证连续最优点确实一致。

```python
import math
import numpy as np

def cbrt_real(x: float) -> float:
    # 实数立方根（避免 Python 对负数开 1/3 次方变复数）
    return x**(1/3) if x >= 0 else -((-x)**(1/3))

def depressed_cubic_real_roots(p: float, q: float, eps: float=1e-12):
    """解 t^3 + p t + q = 0，返回所有实根"""
    Delta = (q/2)**2 + (p/3)**3
    if Delta > eps:
        u = cbrt_real(-q/2 + math.sqrt(Delta))
        v = cbrt_real(-q/2 - math.sqrt(Delta))
        return [u + v]
    if abs(Delta) <= eps:
        u = cbrt_real(-q/2)
        return [2*u, -u]  # 重根情形（可能重复）
    # 三个实根
    r = math.sqrt(-p/3)
    arg = (-q/2) / (r**3)
    arg = max(-1.0, min(1.0, arg))
    phi = math.acos(arg)
    return [2*r*math.cos((phi + 2*math.pi*k)/3) for k in range(3)]

def B_on_abS(x, y, z, S, a):
    """连续情形：ab=S => b=S/a"""
    b = S / a
    p = x / a
    l = y / b
    return p*l*z*(2*a*b-(a+b)) + a*(l-1.0)

def stationary_a_roots(x, y, z, S):
    """解驻点方程：2y a^3 - (xyz+S)a^2 + xyz S = 0，返回所有实根"""
    X = x*y*z
    A = - (X + S) / (2*y)   # a^3 + A a^2 + C = 0
    C = (X * S) / (2*y)

    # a = t - A/3 => t^3 + p t + q = 0
    p = - (A*A)/3
    q = 2*(A**3)/27 + C

    t_roots = depressed_cubic_real_roots(p, q)
    a_roots = [t - A/3 for t in t_roots]

    # 去重
    out = []
    for r in a_roots:
        if all(abs(r-u) > 1e-9 for u in out):
            out.append(r)
    return out

def continuous_opt_abS(x, y, z, S):
    """无遍历：候选点=端点+三次方程实根，取最大"""
    a_min = S / y
    a_max = x
    if a_min > a_max:
        raise ValueError("No feasible solution: S/y > x")

    cand = [a_min, a_max]
    for r in stationary_a_roots(x, y, z, S):
        if a_min <= r <= a_max:
            cand.append(r)

    best = None
    for a in cand:
        val = B_on_abS(x, y, z, S, a)
        if best is None or val > best[0]:
            best = (val, a, S/a)
    return best, (a_min, a_max), cand

# ---------- 验证：与密集网格最大值一致 ----------
def dense_grid_max(x, y, z, S, a_min, a_max, n=200000):
    best = (-1e300, None)
    for a in np.linspace(a_min, a_max, n):
        val = B_on_abS(x,y,z,S,a)
        if val > best[0]:
            best = (val, a)
    return best

if __name__ == "__main__":
    x,y,z,S = 200,200,4,2000
    best, interval, cand = continuous_opt_abS(x,y,z,S)
    grid_best = dense_grid_max(x,y,z,S, *interval, n=200000)
    print("Closed-form candidates best:", best)
    print("Grid best (approx):", grid_best)
    print("Interval:", interval)
    print("Candidates:", cand)
