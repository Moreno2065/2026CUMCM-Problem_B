"""Rigorous outward-enclosing interval arithmetic over FLINT Arb balls.

Spec basis: Formal Global Optimality Proof Loop Engineering Specification
sections 12, 13, 25.  Every certificate-path quantity is an ``Ivl``: an
interval represented internally by a ``flint.arb`` ball, so all elementary
operations (including sin/cos/atan2/sqrt) carry rigorous error enclosure.
Tri-state comparisons (section 13) never guess: overlapping intervals yield
``Tri.UNKNOWN`` and the caller must subdivide or raise precision.

Decimal constants use string construction (``Ivl.from_decimal``) so the
enclosure covers the exact decimal value; binary floats use
``Ivl.from_float`` which encloses the exact binary value.  ``pi`` comes from
``arb.pi()`` and epsilon = pi/180 is derived from it, never from
``math.radians``.
"""

from __future__ import annotations

import enum
import math

import flint
from flint import arb as _arb


DEFAULT_PRECISION_BITS = 128
_PRECISION_LADDER = (128, 256, 512)


def set_precision_bits(n: int) -> None:
    if n < 53 or n > 8192:
        raise ValueError("precision out of supported range")
    flint.ctx.prec = int(n)


def get_precision_bits() -> int:
    return int(flint.ctx.prec)


def default_precision() -> int:
    return DEFAULT_PRECISION_BITS


set_precision_bits(DEFAULT_PRECISION_BITS)


class Tri(enum.Enum):
    """Tri-state comparison outcome (spec section 13)."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"

    def definite(self) -> bool:
        return self is not Tri.UNKNOWN


class Ivl:
    """An interval [lo, hi] backed by a FLINT arb ball."""

    __slots__ = ("_b",)

    def __init__(self, ball):
        if isinstance(ball, Ivl):
            ball = ball._b
        if not isinstance(ball, _arb):
            raise TypeError("Ivl wraps a flint.arb ball")
        self._b = ball

    # ------------------------------------------------------------------
    # constructors
    # ------------------------------------------------------------------
    @staticmethod
    def from_arb(ball) -> "Ivl":
        return Ivl(_arb(ball))

    @staticmethod
    def from_float(x: float) -> "Ivl":
        if not math.isfinite(x):
            raise ValueError("non-finite float")
        return Ivl(_arb(float(x)))

    @staticmethod
    def from_int(n: int) -> "Ivl":
        return Ivl(_arb(int(n)))

    @staticmethod
    def from_decimal(s: str) -> "Ivl":
        """Enclose the exact decimal value of ``s``."""
        return Ivl(_arb(str(s)))

    @staticmethod
    def from_bounds(lo, hi) -> "Ivl":
        """Enclose every value between lo and hi (floats or decimal strings).

        If lo/hi overlap due to rounding noise the hull is returned; a
        definite gap with lo > hi raises.
        """
        lo_b = lo._b if isinstance(lo, Ivl) else (
            _arb(str(lo)) if isinstance(lo, str) else _arb(lo))
        hi_b = hi._b if isinstance(hi, Ivl) else (
            _arb(str(hi)) if isinstance(hi, str) else _arb(hi))
        if not (lo_b <= hi_b):
            lo_l, hi_u = lo_b.lower(), hi_b.upper()
            if lo_l <= hi_u:
                pass  # endpoint balls overlap; the hull below covers both
            else:
                raise ValueError("empty interval bounds")
        lo_l = lo_b.lower()
        hi_u = hi_b.upper()
        return Ivl(_arb((lo_l + hi_u) / 2, (hi_u - lo_l) / 2))

    def bisect(self) -> tuple["Ivl", "Ivl"]:
        """Split into two children covering self, built from arb endpoints.

        No float round-trip: endpoint drift per level is bounded by the
        30-bit radius granularity of the arb ball constructor, which shrinks
        with the box width instead of accumulating.
        """
        lo = self._b.lower()
        hi = self._b.upper()
        mid = (lo + hi) / 2
        left = Ivl(_arb((lo + mid) / 2, (mid - lo) / 2))
        right = Ivl(_arb((mid + hi) / 2, (hi - mid) / 2))
        return left, right

    def clamp(self, lo_ball, hi_ball) -> "Ivl | None":
        """Intersect with the exact interval [lo_ball, hi_ball] (arbs)."""
        a = max(self._b.lower(), lo_ball)
        b = min(self._b.upper(), hi_ball)
        if bool(a > b):
            return None
        lo_l, hi_u = a.lower(), b.upper()
        if not (lo_l <= hi_u):
            return None
        return Ivl(_arb((lo_l + hi_u) / 2, (hi_u - lo_l) / 2))

    def intersect(self, other: "Ivl") -> "Ivl | None":
        """Tight intersection; None if definitely disjoint."""
        lo = max(self._b.lower(), other._b.lower())
        hi = min(self._b.upper(), other._b.upper())
        if lo <= hi:
            return Ivl(_arb((lo + hi) / 2, (hi - lo) / 2))
        lo_l, hi_u = lo.lower(), hi.upper()
        if lo_l <= hi_u:
            # endpoint balls overlap marginally: return the hull of the range
            return Ivl(_arb((lo_l + hi_u) / 2, (hi_u - lo_l) / 2))
        return None

    @staticmethod
    def point(value) -> "Ivl":
        if isinstance(value, str):
            return Ivl.from_decimal(value)
        if isinstance(value, float):
            return Ivl.from_float(value)
        if isinstance(value, int):
            return Ivl.from_int(value)
        if isinstance(value, Ivl):
            return value
        if isinstance(value, _arb):
            return Ivl(value)
        raise TypeError(f"cannot make Ivl from {type(value)}")

    @staticmethod
    def pi() -> "Ivl":
        return Ivl(_arb.pi())

    @staticmethod
    def hull(a: "Ivl", b: "Ivl") -> "Ivl":
        lo = min(a._b.lower(), b._b.lower())
        hi = max(a._b.upper(), b._b.upper())
        return Ivl(_arb((lo + hi) / 2, (hi - lo) / 2))

    # ------------------------------------------------------------------
    # bounds extraction
    # ------------------------------------------------------------------
    def lower_arb(self):
        """arb ball enclosing the true lower endpoint."""
        return self._b.lower()

    def upper_arb(self):
        """arb ball enclosing the true upper endpoint."""
        return self._b.upper()

    def lower_float(self) -> float:
        """float guaranteed <= true lower endpoint (outward adjusted)."""
        v = float(self._b.lower())
        for _ in range(4):
            v = math.nextafter(v, -math.inf)
        return v

    def upper_float(self) -> float:
        """float guaranteed >= true upper endpoint (outward adjusted)."""
        v = float(self._b.upper())
        for _ in range(4):
            v = math.nextafter(v, math.inf)
        return v

    def mid_float(self) -> float:
        return float(self._b.mid())

    def mid_arb(self):
        return self._b.mid()

    def rad_arb(self):
        return self._b.rad()

    def width(self) -> "Ivl":
        return Ivl(self.upper_arb() - self.lower_arb())

    def is_point(self) -> bool:
        return bool(self._b.rad() == 0)

    def contains(self, other) -> bool:
        other_b = other._b if isinstance(other, Ivl) else _arb(other)
        return bool(self._b.contains(other_b))

    def contains_interior(self, other) -> bool:
        other_b = other._b if isinstance(other, Ivl) else _arb(other)
        return bool(self._b.contains_interior(other_b))

    def overlaps(self, other: "Ivl") -> bool:
        lo = max(self.lower_arb(), other.lower_arb())
        hi = min(self.upper_arb(), other.upper_arb())
        return bool(lo <= hi)

    # ------------------------------------------------------------------
    # arithmetic (all outward-enclosing via arb)
    # ------------------------------------------------------------------
    def _coerce(self, other) -> "Ivl":
        return other if isinstance(other, Ivl) else Ivl.point(other)

    def __add__(self, other):
        other = self._coerce(other)
        return Ivl(self._b + other._b)

    __radd__ = __add__

    def __sub__(self, other):
        other = self._coerce(other)
        return Ivl(self._b - other._b)

    def __rsub__(self, other):
        other = self._coerce(other)
        return Ivl(other._b - self._b)

    def __mul__(self, other):
        other = self._coerce(other)
        return Ivl(self._b * other._b)

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self._coerce(other)
        if other.contains(0):
            raise ZeroDivisionError("interval division straddles zero")
        return Ivl(self._b / other._b)

    def __neg__(self):
        return Ivl(-self._b)

    def __abs__(self):
        return Ivl(abs(self._b))

    def sqrt(self) -> "Ivl":
        lo = self._b.lower()
        hi = self._b.upper()
        zero = _arb(0)
        lo_c = max(lo, zero)
        if not (lo_c <= hi):
            raise ValueError("sqrt of negative interval")
        a = _arb(lo_c).sqrt()
        b = _arb(hi).sqrt()
        return Ivl(_arb((a + b) / 2, (b - a) / 2))

    def square(self) -> "Ivl":
        lo = self._b.lower()
        hi = self._b.upper()
        if bool(lo >= 0):
            a, b = lo * lo, hi * hi
        elif bool(hi <= 0):
            a, b = hi * hi, lo * lo
        else:
            a = _arb(0)
            b = max(lo * lo, hi * hi)
        return Ivl(_arb((a + b) / 2, (b - a) / 2))

    def sin(self) -> "Ivl":
        return Ivl(self._b.sin())

    def cos(self) -> "Ivl":
        return Ivl(self._b.cos())

    def atan2(self, x: "Ivl") -> "Ivl":
        """Enclosure of atan2(self, x); caller must exclude the origin."""
        x = self._coerce(x)
        if self.contains(0) and x.contains(0):
            raise ValueError("atan2 box contains the origin")
        return Ivl(_arb.atan2(self._b, x._b))

    @staticmethod
    def min(a: "Ivl", b: "Ivl") -> "Ivl":
        lo = min(a._b.lower(), b._b.lower())
        hi = min(a._b.upper(), b._b.upper())
        return Ivl(_arb((lo + hi) / 2, (hi - lo) / 2))

    @staticmethod
    def max(a: "Ivl", b: "Ivl") -> "Ivl":
        lo = max(a._b.lower(), b._b.lower())
        hi = max(a._b.upper(), b._b.upper())
        return Ivl(_arb((lo + hi) / 2, (hi - lo) / 2))

    # ------------------------------------------------------------------
    # tri-state comparisons (spec section 13)
    # ------------------------------------------------------------------
    @staticmethod
    def lt(a, b) -> Tri:
        a = a if isinstance(a, Ivl) else Ivl.point(a)
        b = b if isinstance(b, Ivl) else Ivl.point(b)
        if bool(a._b < b._b):
            return Tri.TRUE
        if bool(a._b >= b._b):
            return Tri.FALSE
        return Tri.UNKNOWN

    @staticmethod
    def le(a, b) -> Tri:
        a = a if isinstance(a, Ivl) else Ivl.point(a)
        b = b if isinstance(b, Ivl) else Ivl.point(b)
        if bool(a._b <= b._b):
            return Tri.TRUE
        if bool(a._b > b._b):
            return Tri.FALSE
        return Tri.UNKNOWN

    @staticmethod
    def gt(a, b) -> Tri:
        return Ivl.lt(b, a)

    @staticmethod
    def ge(a, b) -> Tri:
        return Ivl.le(b, a)

    @staticmethod
    def sign(a) -> Tri:
        """TRUE => definitely > 0, FALSE => definitely < 0, else UNKNOWN."""
        a = a if isinstance(a, Ivl) else Ivl.point(a)
        if bool(a._b > 0):
            return Tri.TRUE
        if bool(a._b < 0):
            return Tri.FALSE
        return Tri.UNKNOWN

    # ------------------------------------------------------------------
    # serialization (decimal enclosures, spec section 39)
    # ------------------------------------------------------------------
    def to_decimal_enclosure(self, digits: int = 25) -> tuple[str, str]:
        """(lo, hi) decimal strings provably enclosing the interval.

        The arb endpoints are printed with ``digits`` significant digits and
        the final printed digit is then bumped one unit outward, which covers
        both the arb rounding of the endpoint and the decimal print rounding.
        """
        lo = self._b.lower()
        hi = self._b.upper()
        lo_s = _decimal_outward(lo, digits, toward_negative=True)
        hi_s = _decimal_outward(hi, digits, toward_negative=False)
        return lo_s, hi_s

    def __repr__(self) -> str:
        return f"Ivl({self._b})"


def _decimal_outward(ball, digits: int, toward_negative: bool) -> str:
    """Decimal string of an arb endpoint ball, provably outward.

    The printed midpoint is rounded to nearest at ``digits + 8`` digits; the
    bump covers that print rounding (3 units of the last printed digit) plus
    twice the endpoint ball's own radius (its ``str(8)`` print rounds to
    nearest, factor 2 covers it with wide margin).  Final quantization is
    ROUND_FLOOR / ROUND_CEILING (toward -inf / +inf), which is the correct
    outward direction for either sign of the endpoint.
    """
    from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext

    s = ball.str(digits + 8, radius=False, more=False)
    rad_s = ball.rad().str(8, radius=False, more=False)
    with localcontext() as ctx:
        ctx.prec = digits + 40
        d = Decimal(s)
        rad = Decimal(rad_s) * 2
        exp = (d.adjusted() if d != 0 else 0) - (digits + 8) + 1
        quantum = Decimal(1).scaleb(exp)
        bump = quantum * 3 + rad
        if toward_negative:
            out = (d - bump).quantize(quantum, rounding=ROUND_FLOOR)
        else:
            out = (d + bump).quantize(quantum, rounding=ROUND_CEILING)
    return format(out, "f")


def epsilon_radians(epsilon_deg: float = 1.0) -> Ivl:
    """Frozen one-degree bearing error as a rigorous interval (spec s.12)."""
    if float(epsilon_deg) != 1.0:
        raise ValueError("frozen model uses exactly one degree")
    return Ivl.pi() / Ivl.from_int(180)
