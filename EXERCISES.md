# Reference Manual Case Studies (`EXERCISES.md`)

This guide provides textbook case studies extracted directly from the official **Tessent Shell Reference Manual** (`tshell_ref.pdf`, v2026.2, Rev 43).

These exercises allow you to inspect, replay, and analyze real-world DRC violations (**T3, T4, T5, C1, D1**) as documented in the Siemens EDA manuals.

---

## Case Study Catalog

| Case ID | Rule | Description | PDF Page | Printed Page |
| :--- | :--- | :--- | :--- | :--- |
| `case01` | **T3** | Scan chain trace blocked at gate | 4522–4524 | 12-790–12-792 |
| `case02` | **T4** | Scan chain trace clock inputs violation | 4525–4528 | 12-793–12-796 |
| `case03` | **T5** | Clock has `X` value during scan chain trace | 4529–4531 | 12-797–12-799 |
| `case04` | **C1** | Clock Rule C1: Clock PIs off failed to force off clock line | 3809–3814 | 12-77–12-82 |
| `case05` | **D1** | Data Rule D1: Scan cell disturbed during `load_unload` | 3863–3866 | 12-131–12-134 |

---

## How to Work on a Case Study

### 1. List Available Cases
```bash
tshell-exercises list
# or: python3 exercises.py list
```

### 2. Initialize a Workspace for a Case
Create a dedicated workspace folder for your study:
```bash
tshell-exercises init case01 --dir work/case01-study-1
```
This initializes:
- `work/case01-study-1/case.json`: Metadata for the selected case.
- `work/case01-study-1/analysis.txt`: Note sheet for recording your observations and root cause analysis.

### 3. Replay the Reference Transcript
Replay the exact console messages and DRC transcript from the reference manual:
```bash
tshell-exercises run --dir work/case01-study-1
```

### 4. Inspect Source Commands from the Manual
View the exact verbatim Tessent command sequence documented in the manual:
```bash
tshell-exercises commands --dir work/case01-study-1
```

### 5. Read the Original Manual Page
Extract and view the text directly from the specified manual page:
```bash
tshell-exercises source --dir work/case01-study-1 --page 4522
```

---

## Notes & Limitations

- The transcripts and rule excerpts are loaded from `tessent_core/knowledge_db.json` without requiring the proprietary PDF at runtime.
- These case studies are designed for understanding DRC rule semantics and debug methodologies; they do not replace full commercial cell libraries or complete industrial netlists.
- Reading and replaying book excerpts requires only the standard Python library. To run older Verilog exercises or the RTL demo, install Icarus Verilog (`iverilog` and `vvp`); on macOS with Homebrew, run `brew install icarus-verilog`. Run the demo with `./rtl/run.sh`.
- RTL simulation runs locally with the permissions of the current user, so only run designs and testbenches you trust.
