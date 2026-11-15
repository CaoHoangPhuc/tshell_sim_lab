# Fix DRC, ATPG, and Netlist Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the 6 reviewer-identified discrepancies in scan path tracing (T3), test procedure DRC checks (T4/T5/D1), clock off-state rule (C1), ATPG control pin inference vs. pure combinational circuits, continuous assignment 4-state Z propagation, and reference oracle test verification against Tessent Shell 2026.2 specifications.

**Architecture:** 
1. Separate continuous assignments (`ASSIGN`) from primitive buffers (`BUF`) in `tessent_core/netlist.py` so wire aliases preserve `Logic4.Z` while primitive buffers continue to coerce `Z` to `X`.
2. Restrict ATPG control-pin heuristics in `tessent_core/atpg.py` to sequential designs containing flip-flops (`DFF`) or configured scan chains, ensuring pure combinational primary inputs/outputs (`reset`, `so`) remain regular data ports for pattern application and strobe observation.
3. Update DRC in `tessent_core/drc.py`: allow clock off-states of 0 or 1 under rule C1; implement topological directed-graph scan chain path tracing for T3 to catch disconnected chains and prevent false positives from unrelated branches; check active shift clock events for T4, invalid states/active reset for T5, and data disturb for D1 without requiring anomaly flags.
4. Replace anomaly-injected oracle tests in `tests/test_reference_cases.py` with true algorithmic tests on reference circuit topologies conforming to the Reference Manual.

**Tech Stack:** Python 3.9+, standard library, pytest, PyMuPDF (optional manual reference), Icarus Verilog (`iverilog`/`vvp`).

**Spec:** User review findings aligning with `tshell_ref.pdf` (Reference Manual v2026.2 Rev 43 p. 3809, 3863, 4520-4531) and `docs/plans/2026-11-14-tshell-roadmap.md`.

## Global Constraints

- Must pass on Python 3.9 through 3.14 without new external dependencies.
- All existing 75 testcases (plus newly added regression tests) must pass.
- No production code without a failing test first (TDD).
- Zero-Asset Policy: Do not bundle or commit PDF files or manual copyrighted text.

## Review Focus

1. `assign y = a;` where `a` has high-impedance `Z` must propagate `y = Z`, while `buf b1(y, a);` must propagate `y = X`.
2. Pure combinational circuits with inputs named `reset` or outputs named `so` must achieve full stuck-at fault coverage when exhaustive or suitable patterns are applied.
3. Edge-triggered DFF scan cells with clock off-state defined as 1 (e.g., active-low clocks) must pass rule C1 without false violations.
4. Scan chains with broken inputs or outputs must fail T3 with specific blocked gate details, while unrelated gates branching off scan pins must not cause false T3 violations.
5. Rule checks T4, T5, and D1 must execute algorithmically based on circuit connectivity and shift procedure clocks/resets rather than requiring `injected_anomalies`.

---

### Task 1: Fix continuous assignment Z-value handling in netlist and logic4

**Files:**
- Modify: `tessent_core/netlist.py:75-90, 405-415`
- Test: `tests/test_netlist_regressions.py`

- [ ] Write failing test in `tests/test_netlist_regressions.py` checking that `assign y = a;` with `a = Logic4.Z` produces `y = Logic4.Z`, while `buf b1(y, a);` produces `y = Logic4.X`.
- [ ] Run pytest to verify the test fails (`y == Logic4.X` instead of `Logic4.Z`).
- [ ] Update `Gate.evaluate_output` in `tessent_core/netlist.py` to support `ASSIGN`/`WIRE` gate type returning input directly.
- [ ] Update `_SubsetParser` in `tessent_core/netlist.py` to create `Gate(..., "ASSIGN", ...)` instead of `"BUF"` for continuous assignments.
- [ ] Run pytest to verify the test passes and existing tests remain green.
- [ ] Commit changes with descriptive commit message.

---

### Task 2: Fix ATPG control pin inference on combinational circuits

**Files:**
- Modify: `tessent_core/atpg.py:60-95, 105-150`
- Test: `tests/test_atpg_regressions.py`

- [ ] Write failing test in `tests/test_atpg_regressions.py` for `assign y = reset;` showing SA0 is detected (DS) and 100% coverage, and for `assign so = a;` showing `so` is observed and achieves 100% coverage.
- [ ] Run pytest to verify tests fail (currently `reset SA0` is `ND` and coverage on `so = a` is 0%).
- [ ] Refactor `get_control_pins(circuit)` in `tessent_core/atpg.py` so that heuristic names (`reset`, `scan_en`, `scan_in`, `scan_out`) are only inferred if the circuit has sequential memory elements (`DFF`) or scan cells.
- [ ] In `execute_test_pattern`, only perform reset pulse and exclude pins from `data_pis` / `obs_pos` if they are confirmed control pins.
- [ ] Run pytest to verify both tests pass.
- [ ] Commit changes.

---

### Task 3: Fix DRC Rule C1 for clock off-state equal to 1

**Files:**
- Modify: `tessent_core/drc.py:121-145`
- Test: `tests/test_drc_regressions.py`

- [ ] Write failing test in `tests/test_drc_regressions.py` for a circuit with clock off-state = 1 (active-low clock) where clock line is stable at 1, verifying C1 is NOT reported.
- [ ] Run pytest to verify test fails (currently reports C1-1 violation).
- [ ] In `tessent_core/drc.py`, evaluate C1 against the specified `off_val` (or stable binary value 0 or 1 for DFF scan cells, checking that clock is not `Logic4.X`).
- [ ] Run pytest to verify test passes.
- [ ] Commit changes.

---

### Task 4: Fix DRC Rule T3 Sensitized Scan Path Tracing

**Files:**
- Modify: `tessent_core/drc.py:193-249`
- Test: `tests/test_drc_regressions.py`

- [ ] Write failing tests in `tests/test_drc_regressions.py`:
  - Broken scan-in connection: `scan_in` does not connect to the first cell $\rightarrow$ must report T3 violation.
  - Broken scan-out connection: last cell does not connect to `scan_out` $\rightarrow$ must report T3 violation.
  - Unrelated branch: `scan_in` fans out to an unrelated blocked gate $\rightarrow$ must NOT report T3 violation.
- [ ] Run pytest to verify tests fail.
- [ ] Reimplement T3 tracing in `tessent_core/drc.py` using directed topological path traversal from `scan_in` through gates to each cell in order, and from the final cell to `scan_out`.
- [ ] Only inspect gating conditions along the actual sensitized scan path.
- [ ] Run pytest to verify tests pass.
- [ ] Commit changes.

---

### Task 5: Fix DRC Rules T4, T5, and D1 algorithmic checking

**Files:**
- Modify: `tessent_core/drc.py:166-191, 270-297`
- Test: `tests/test_drc_regressions.py`

- [ ] Write tests in `tests/test_drc_regressions.py`:
  - T4: scan chain cell clock not connected to a pulsing clock defined in clocks $\rightarrow$ reports T4 violation without `injected_anomalies`.
  - T5: scan cell with X or active reset during shift $\rightarrow$ reports T5 violation.
  - D1: scan cell disturbed by active reset during shift / load_unload $\rightarrow$ reports D1 violation.
- [ ] Run pytest to verify tests fail or reflect incomplete check.
- [ ] Update `tessent_core/drc.py` to perform these checks algorithmically on circuit structure without needing `injected_anomalies`.
- [ ] Run pytest to verify all tests pass.
- [ ] Commit changes.

---

### Task 6: Refactor test_reference_cases.py to verify real circuit behavior

**Files:**
- Modify: `tests/test_reference_cases.py:100-130`
- Test: `tests/test_reference_cases.py`

- [ ] Update `test_t3_t4_t5_reference_oracles` and `test_d1_reference_oracle` to construct actual circuit topologies representing blocked scan path (T3), unclocked cell (T4), X/active clock during shift (T5), and active reset disturb (D1).
- [ ] Verify violations are caught algorithmically without passing `injected_anomalies`.
- [ ] Ensure `DRCEngine` is initialized with default catalog (JSON) rather than passing `.pdf` to `json.loads`.
- [ ] Run full pytest suite across all test files.
- [ ] Commit changes.

---

### Task 7: Full verification and Pull Request creation

**Files:**
- Entire repository

- [ ] Run full test suite: `python3 -m pytest -v`.
- [ ] Check git diff and git log.
- [ ] Push branch `fix/drc-atpg-netlist-semantics` to `origin`.
- [ ] Create Pull Request using `gh pr create` with comprehensive description detailing the 6 review points and their fixes.
