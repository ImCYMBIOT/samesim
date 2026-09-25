"""
Portable math: transcendental functions and random variates that return
bit-identical results on every platform.

Why this exists: IEEE 754 requires correctly rounded results only for
+, -, *, /, sqrt and a few exact operations (frexp, ldexp, floor, ...).
log, exp, pow, sin and the rest come from each platform's C library, and
those libraries round differently -- glibc's log is not correctly rounded
either (about 1 in 1,500 results differs from the exact value). Python's
random.expovariate, gauss, normalvariate and lognormvariate are built on
them, and CPython even computes random.NV_MAGICCONST with libm exp at
import time.

A last-bit difference is usually harmless, but not in an event-driven
simulation, where an exponential delay becomes an exact event time: a
different last bit reorders events and the run diverges. It first surfaced
as golden traces recorded on Linux failing on macOS and Windows.

Everything here is built only from IEEE-exact operations, evaluated in a
fixed order, so it is deterministic everywhere. Accuracy is within a few
ulps of the true value (checked in tests/unit/domain/test_portable_math.py),
not correctly rounded -- the goal is identical results, not the last bit
of accuracy.

Plugins and core must use these instead of the math/random equivalents;
tests/unit/test_portable_math_usage.py fails the build otherwise.

The random variates consume the RNG stream exactly as CPython's do
(expovariate: one random(); normalvariate: Kinderman-Monahan, two per
attempt), so swapping them in changes a run only where libm rounded
differently.
"""
from __future__ import annotations

import math
from random import Random

# ln 2 split fdlibm-style: _LN2_HI has 21 trailing zero bits, so k * _LN2_HI
# is exact for |k| < 2**21 -- the range reduction adds no rounding error.
_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10
_INV_LN2 = 1.44269504088896338700e+00
_SQRT_HALF = 0.70710678118654752440

# log(m) = 2*atanh(s), s = (m-1)/(m+1): 2*(s + s^3/3 + s^5/5 + ...).
# With m in [sqrt(1/2), sqrt(2)), |s| <= 0.1716, and the 12 terms below
# bring truncation error under 1e-18 relative.
_LOG_C = tuple(2.0 / (2 * k + 1) for k in range(1, 13))

# exp(r) for |r| <= ln2/2 by Taylor series to r^14 (truncation < 1e-18).
_EXP_C = tuple(1.0 / math.factorial(k) for k in range(14, -1, -1))

# CPython's random.NV_MAGICCONST = 4 * exp(-0.5) / sqrt(2.0), computed at
# import time with the platform's exp. Fixed here instead.
NV_MAGICCONST = 1.7155277699214135

_EXP_MAX = 709.782712893384     # exp(x) overflows above this
_EXP_MIN = -745.1332191019412   # exp(x) underflows to 0 below this


def log(x: float) -> float:
    """Natural logarithm, identical on every platform. Mirrors math.log's
    errors: ValueError for x <= 0; inf for inf; nan for nan."""
    if x != x or x == math.inf:
        return x
    if x <= 0.0:
        raise ValueError("math domain error")
    m, e = math.frexp(x)                 # exact: x = m * 2**e, 0.5 <= m < 1
    if m < _SQRT_HALF:
        m *= 2.0                         # exact
        e -= 1
    f = m - 1.0                          # exact (Sterbenz)
    s = f / (2.0 + f)
    z = s * s
    series = 0.0
    for c in reversed(_LOG_C):
        series = series * z + c
    log_m = 2.0 * s + s * (z * series)
    return e * _LN2_HI + (log_m + e * _LN2_LO)


def exp(x: float) -> float:
    """e**x, identical on every platform. Mirrors math.exp: OverflowError
    above ~709.78; 0.0 below ~-745.13; nan for nan."""
    if x != x:
        return x
    if x > _EXP_MAX:
        raise OverflowError("math range error")
    if x < _EXP_MIN:
        return 0.0
    k = math.floor(x * _INV_LN2 + 0.5)
    r = (x - k * _LN2_HI) - k * _LN2_LO  # |r| <= ~0.347
    p = 0.0
    for c in _EXP_C:
        p = p * r + c
    return math.ldexp(p, k)


def ipow(x: float, n: int) -> float:
    """x**n for a non-negative integer n by repeated multiplication.

    Builtin ** on floats calls the platform's pow(). For small n (a count of
    neighbors, contacts, rounds) n multiplications are cheap and portable.
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError(f"ipow needs a non-negative int exponent, got {n!r}")
    result = 1.0
    for _ in range(n):
        result *= x
    return result


def expovariate(rng: Random, lambd: float) -> float:
    """Exponential variate with rate lambd; same RNG use as Random.expovariate."""
    return -log(1.0 - rng.random()) / lambd


def normalvariate(rng: Random, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Normal variate by Kinderman-Monahan, exactly as Random.normalvariate
    draws it, with portable log and a fixed NV_MAGICCONST."""
    while True:
        u1 = rng.random()
        u2 = 1.0 - rng.random()
        z = NV_MAGICCONST * (u1 - 0.5) / u2
        zz = z * z / 4.0
        if zz <= -log(u2):
            break
    return mu + z * sigma


def lognormvariate(rng: Random, mu: float, sigma: float) -> float:
    """Log-normal variate; same RNG use as Random.lognormvariate."""
    return exp(normalvariate(rng, mu, sigma))
