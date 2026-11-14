#!/usr/bin/env python3
"""Small, binary, educational scan model; this is not a Tessent emulator."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


def bit(value: int) -> int:
    if value not in (0, 1):
        raise ValueError(f"expected a binary value, got {value!r}")
    return int(value)


@dataclass(frozen=True)
class Fault:
    """Force one named signal to its stuck-at value throughout a run."""

    node: str
    value: int

    def __post_init__(self) -> None:
        if self.node not in {"q0", "q1", "d0", "d1", "y"}:
            raise ValueError(f"unknown fault node: {self.node}")
        bit(self.value)


class ScanCircuit:
    """Two scan flops: SI -> q0 -> q1 -> SO; SO is sampled before the edge.

    Functional mode: d0 = a XOR q1, d1 = q0 AND b, y = q0 XOR q1.
    Both flops update at the same edge. All values start at zero.
    """

    def __init__(self, fault: Fault | None = None) -> None:
        self.fault = fault
        self._q0 = 0
        self._q1 = 0

    def _signal(self, name: str, value: int) -> int:
        return self.fault.value if self.fault and self.fault.node == name else value

    @property
    def state(self) -> tuple[int, int]:
        return self._signal("q0", self._q0), self._signal("q1", self._q1)

    def shift(self, scan_in: int) -> int:
        scan_in = bit(scan_in)
        q0, q1 = self.state
        self._q0, self._q1 = scan_in, q0
        return q1

    def capture(self, a: int, b: int) -> None:
        a, b = bit(a), bit(b)
        q0, q1 = self.state
        self._q0, self._q1 = self._signal("d0", a ^ q1), self._signal("d1", q0 & b)

    def output(self) -> int:
        q0, q1 = self.state
        return self._signal("y", q0 ^ q1)


@dataclass(frozen=True)
class CaseResult:
    name: str
    fault: Fault | None
    expected_y: int
    observed_y: int
    expected_scan: tuple[int, int]
    observed_scan: tuple[int, int]
    detected: bool
    expected_detected: bool

    @property
    def passed(self) -> bool:
        return self.detected == self.expected_detected


def run_case(name: str) -> CaseResult:
    # Values for scan_in are listed in chronological order.
    scenarios = {
        "good": ((0, 1), None, False),
        "detected": ((0, 1), Fault("q0", 0), True),
        "masked": ((0, 0), Fault("q0", 0), False),
    }
    if name not in scenarios:
        raise ValueError(f"unknown case: {name}")
    scan_in, fault, expected_detected = scenarios[name]
    reference, device = ScanCircuit(), ScanCircuit(fault)
    for value in scan_in:
        reference.shift(value)
        device.shift(value)
    for circuit in (reference, device):
        circuit.capture(a=0, b=1)
    expected_y, observed_y = reference.output(), device.output()
    expected_scan = tuple(reference.shift(0) for _ in range(2))
    observed_scan = tuple(device.shift(0) for _ in range(2))
    detected = (expected_y, expected_scan) != (observed_y, observed_scan)
    return CaseResult(name, fault, expected_y, observed_y, expected_scan,
                      observed_scan, detected, expected_detected)


def main() -> int:
    parser = argparse.ArgumentParser(description="Educational scan and stuck-at fault simulation (not Tessent).")
    parser.add_argument("--case", choices=("all", "good", "detected", "masked"), default="all")
    args = parser.parse_args()
    cases = ("good", "detected", "masked") if args.case == "all" else (args.case,)
    passed = True
    for name in cases:
        result = run_case(name)
        fault = f"{result.fault.node} stuck-at-{result.fault.value}" if result.fault else "none"
        print(f"[{ 'PASS' if result.passed else 'FAIL' }] {name}: injected fault={fault}")
        print(f"  expected y={result.expected_y}, scan-out={result.expected_scan}")
        print(f"  observed y={result.observed_y}, scan-out={result.observed_scan}")
        print(f"  mismatch detected={result.detected}; expected detection={result.expected_detected}")
        passed &= result.passed
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
