"""Regression tests for rigorous polar branch-and-bound enclosures."""

from src.q2.formal.polar_bb import polar_max
from src.q2.formal.rigorous_arithmetic import Ivl


def test_polar_max_keeps_the_stopping_piece_in_its_upper_enclosure():
    """A tolerance stop must still enclose the just-popped live box.

    The analytic maximum of rho + 1000 phi is at
    (1500, pi / 180).  This deliberately loose tolerance exercises the
    early-stop path where the popped heap item is not retained in ``heap``.
    """
    result = polar_max(
        lambda rho, phi: rho + Ivl.from_int(1000) * phi,
        lambda rho, phi: rho + 1000.0 * phi,
        target_tol=1e-3,
    )
    exact_max = Ivl.from_int(1500) + Ivl.from_int(1000) * Ivl.pi() / Ivl.from_int(180)

    assert result.converged
    assert result.value.contains(exact_max)


def test_polar_max_uses_domain_boundary_witness_to_limit_splitting():
    """A monotone affine objective should nearly close from its boundary.

    The rigorous interval enclosure over the root box and the verified value
    near the maximizing corner give a strong incumbent.  A few subdivisions
    remain necessary because Arb ball radii outwardly widen the root box.
    """
    result = polar_max(
        lambda rho, phi: rho + Ivl.from_int(1000) * phi,
        lambda rho, phi: rho + 1000.0 * phi,
        target_tol=1e-9,
    )
    exact_max = (
        Ivl.from_int(1500)
        + Ivl.from_int(1000) * Ivl.pi() / Ivl.from_int(180)
    )

    assert result.converged
    assert result.value.contains(exact_max)
    assert result.pieces_evaluated <= 32
