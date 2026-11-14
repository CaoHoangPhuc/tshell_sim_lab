"""4-state logic system {0, 1, X, Z} conforming to IEEE 1164 & Verilog standards."""

from __future__ import annotations

from enum import Enum


class Logic4(Enum):
    ZERO = "0"
    ONE = "1"
    X = "X"  # Unknown / uninitialized / glitch
    Z = "Z"  # High-impedance

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_val(cls, val: object) -> Logic4:
        if isinstance(val, Logic4):
            return val
        s = str(val).strip().upper()
        if s in ("0", "FALSE", "LOW"):
            return cls.ZERO
        if s in ("1", "TRUE", "HIGH"):
            return cls.ONE
        if s in ("Z", "HIGHZ"):
            return cls.Z
        return cls.X


# Truth tables for 4-state logic
def buf4(a: Logic4) -> Logic4:
    if a == Logic4.ZERO:
        return Logic4.ZERO
    if a == Logic4.ONE:
        return Logic4.ONE
    return Logic4.X


def not4(a: Logic4) -> Logic4:
    if a == Logic4.ZERO:
        return Logic4.ONE
    if a == Logic4.ONE:
        return Logic4.ZERO
    return Logic4.X


def and4(a: Logic4, b: Logic4) -> Logic4:
    # 0 dominates in AND
    if a == Logic4.ZERO or b == Logic4.ZERO:
        return Logic4.ZERO
    if a == Logic4.ONE and b == Logic4.ONE:
        return Logic4.ONE
    return Logic4.X


def nand4(a: Logic4, b: Logic4) -> Logic4:
    return not4(and4(a, b))


def or4(a: Logic4, b: Logic4) -> Logic4:
    # 1 dominates in OR
    if a == Logic4.ONE or b == Logic4.ONE:
        return Logic4.ONE
    if a == Logic4.ZERO and b == Logic4.ZERO:
        return Logic4.ZERO
    return Logic4.X


def nor4(a: Logic4, b: Logic4) -> Logic4:
    return not4(or4(a, b))


def xor4(a: Logic4, b: Logic4) -> Logic4:
    if a in (Logic4.X, Logic4.Z) or b in (Logic4.X, Logic4.Z):
        return Logic4.X
    return Logic4.ONE if a != b else Logic4.ZERO


def xnor4(a: Logic4, b: Logic4) -> Logic4:
    return not4(xor4(a, b))


def mux21(sel: Logic4, d0: Logic4, d1: Logic4) -> Logic4:
    if sel == Logic4.ZERO:
        return d0
    if sel == Logic4.ONE:
        return d1
    # If sel is X, but both data inputs are identical, output is determined!
    if d0 == d1:
        return d0
    return Logic4.X
