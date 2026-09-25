"""
portable_math: identical bits on every platform, accurate to a few ulps.

The known-answer tables are the point. They were generated once, and every
platform in CI (Linux, macOS and Windows; Python 3.10-3.13) must reproduce
them bit for bit. If one doesn't, a function here relies on something
platform-dependent and the module has failed at its only job.
"""
from __future__ import annotations

import math
import random
from decimal import Context, Decimal

import pytest

from simul8.domain import portable_math as pm

LOG_CASES = [
    (0.1, '-0x1.26bb1bbb55515p+1'),
    (0.5, '-0x1.62e42fefa39efp-1'),
    (0.7071067811865476, '-0x1.62e42fefa39eep-2'),
    (1.0, '0x0.0p+0'),
    (1.0000000001, '0x1.b7cdffffa18d8p-34'),
    (2.0, '0x1.62e42fefa39efp-1'),
    (3.141592653589793, '0x1.250d048e7a1bdp+0'),
    (1e-300, '-0x1.5963447f87fb5p+9'),
    (5e-324, '-0x1.74385446d71c3p+9'),
    (1e+300, '0x1.5963447f87fb5p+9'),
    (0.999999999, '-0x1.12e0be024e4bcp-30'),
]
EXP_CASES = [
    (-700.0, '0x1.14f2b0fb9307fp-1010'),
    (-20.5, '0x1.57a3afeed00acp-30'),
    (-1.0, '0x1.78b56362cef38p-2'),
    (-1e-10, '0x1.ffffffff24190p-1'),
    (0.0, '0x1.0000000000000p+0'),
    (1e-10, '0x1.000000006df38p+0'),
    (0.5, '0x1.a61298e1e069cp+0'),
    (1.0, '0x1.5bf0a8b14576ap+1'),
    (2.302585092994046, '0x1.4000000000001p+3'),
    (88.7, '0x1.f4705bbffae5cp+127'),
    (709.0, '0x1.d422d2be5dc9bp+1022'),
]
EXPOVARIATE_SEED_12345 = ['0x1.6fe67278d8308p-2', '0x1.be9281fa5eea8p-8', '0x1.29ab1422f8e50p+0',
                          '0x1.e4547002bf5cfp-3', '0x1.39b28124d8be1p-2']
LOGNORM_SEED_12345 = ['0x1.3cdd0ff11ec89p+0', '0x1.1677d6937b59ep+1', '0x1.24216c5f8fb7ep+0',
                      '0x1.76bcbe2bf2176p+0', '0x1.5d6e46046f04fp-1']


@pytest.mark.parametrize("x,bits", LOG_CASES)
def test_log_known_answers(x, bits):
    assert pm.log(x).hex() == bits


@pytest.mark.parametrize("x,bits", EXP_CASES)
def test_exp_known_answers(x, bits):
    assert pm.exp(x).hex() == bits


def test_variate_known_answers():
    r = random.Random(12345)
    assert [pm.expovariate(r, 1.5).hex() for _ in range(5)] == EXPOVARIATE_SEED_12345
    r = random.Random(12345)
    assert [pm.lognormvariate(r, 0.3, 0.6).hex() for _ in range(5)] == LOGNORM_SEED_12345


def _ulps(approx: float, exact: float) -> float:
    return abs(approx - exact) / math.ulp(exact)


def test_log_is_within_2_ulp_of_exact():
    ctx, r = Context(prec=50), random.Random(1)
    xs = ([r.random() for _ in range(3000)] + [r.uniform(0.5, 2.0) for _ in range(3000)]
          + [math.ldexp(r.random(), r.randint(-1070, 1020)) for _ in range(3000)])
    worst = max(_ulps(pm.log(x), float(ctx.ln(Decimal(x)))) for x in xs if x > 0 and x != 1.0)
    assert worst <= 2.0, worst


def test_exp_is_within_1_ulp_of_exact():
    ctx, r = Context(prec=50), random.Random(2)
    xs = [r.uniform(-700, 709) for _ in range(3000)] + [r.uniform(-1, 1) for _ in range(3000)]
    worst = max(_ulps(pm.exp(x), float(ctx.exp(Decimal(x)))) for x in xs)
    assert worst <= 1.0, worst


def test_edge_cases_mirror_math():
    assert pm.log(math.inf) == math.inf and math.isnan(pm.log(math.nan))
    for bad in (0.0, -1.0, -math.inf):
        with pytest.raises(ValueError):
            pm.log(bad)
    with pytest.raises(OverflowError):
        pm.exp(710.0)
    assert pm.exp(-746.0) == 0.0 and math.isnan(pm.exp(math.nan))


def test_ipow():
    assert pm.ipow(0.9, 0) == 1.0 and pm.ipow(0.9, 1) == 0.9
    assert pm.ipow(0.9, 3) == 0.9 * 0.9 * 0.9
    for bad in (-1, 2.0, True):
        with pytest.raises(ValueError):
            pm.ipow(0.5, bad)


def test_variates_consume_the_rng_exactly_like_cpython():
    """Same number of random() calls as Random.expovariate / lognormvariate,
    so swapping them in changes a run only where libm rounded differently."""
    for draw_pm, draw_std in [
        (lambda r: pm.expovariate(r, 2.0), lambda r: r.expovariate(2.0)),
        (lambda r: pm.lognormvariate(r, 0.3, 0.6), lambda r: r.lognormvariate(0.3, 0.6)),
    ]:
        a, b = random.Random(7), random.Random(7)
        for _ in range(2000):
            assert math.isclose(draw_pm(a), draw_std(b), rel_tol=1e-14)
        assert a.getstate() == b.getstate()


def test_variates_have_the_right_moments():
    r = random.Random(3)
    xs = [pm.expovariate(r, 4.0) for _ in range(40000)]
    assert abs(sum(xs) / len(xs) - 0.25) < 0.005
    zs = [pm.normalvariate(r, 1.0, 2.0) for _ in range(40000)]
    mean = sum(zs) / len(zs)
    var = sum((z - mean) * (z - mean) for z in zs) / len(zs)
    assert abs(mean - 1.0) < 0.05 and abs(var - 4.0) < 0.12
