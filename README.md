# Tessent Shell Simulation Lab (`tshell_sim_lab`)

An educational Python-based EDA simulation environment modeling Siemens/Mentor **Tessent™ Shell**, Design-for-Testability (DFT) scan chain insertion, Design Rule Checking (DRC), and stuck-at fault ATPG simulation.

> **Note**: This is an educational reference model built purely in Python 3. It simulates Tessent Shell commands, contexts, system modes, and DRC logic without requiring commercial EDA licenses, proprietary cell libraries, or heavy virtualization tools (e.g., Docker / OrbStack).

---

## Key Features

1. **Tessent Mock Shell CLI (`tshell`)**:
   - Interactive Tcl-like command-line interface conforming to standard Tessent Shell conventions.
   - Context switching (`set_context patterns -scan`) and system mode transitions (`setup` ⇄ `analysis`).
   - Verilog netlist loading, pin/clock constraints definition (`add_clocks`, `add_pin_constraints`).
   - Design Rule Checking (DRC) rule querying backed by a pre-compiled in-memory knowledge database (`tessent_core/knowledge_db.json`).
   - Demonstration stuck-at fault injection and coverage output. The current fault grading is not validated and must not be used to assess a design.

2. **Deductive 4-State Logic Engine**:
   - Implements IEEE 1164 / Verilog 4-state logic algebra (`0`, `1`, `X`, `Z`) with proper propagation rules across combinational and sequential gates.

3. **DRC Learning Examples**:
   - A catalog of 600 entries mapped to pages in `tshell_ref.pdf`.
   - Simplified C1/C2 checks and examples for T3/T4/T5/D1. The latter are not yet detected from the actual design; manual excerpts are illustrative, not design results.

4. **Scan Chain Insertion & Fault Simulation**:
   - [insertion.py](file:///Users/phuccao/Workspace/tshell_sim_lab/insertion.py): Automatic multiplexed flip-flop scan chain stitching from high-level circuit specifications to synthesizable Verilog netlists.
   - [scan_sim.py](file:///Users/phuccao/Workspace/tshell_sim_lab/scan_sim.py): Dedicated stuck-at fault simulator demonstrating good machine, detected fault, and masked fault conditions.

---

## Installation & Environment Setup

### Prerequisites
- Python 3.9+ (tested on Python 3.10 – 3.14).
- The Python lab does not require commercial EDA tools or Docker.
- For the optional RTL simulations and RTL exercise tests, install Icarus Verilog (`iverilog` and `vvp`). On macOS with Homebrew: `brew install icarus-verilog`.

### 1. Create and Activate Virtual Environment
```bash
# From the project root
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Package in Editable Mode
```bash
# Core simulation has ZERO runtime dependencies (pure standard library).
# Install with optional development tools (pytest, pymupdf for offline ingestion):
pip install -e ".[dev]"
```

This installs the package and automatically binds the CLI binaries (`tshell`, `tshell-exercises`, `tshell-insertion`, `tshell-scan-sim`) to your environment PATH.

---

## Usage Guide

### 1. Run the Automated Demo
Verify the complete end-to-end workflow in one command:
```bash
tshell --demo
```
This executes the standard DFT flow: context setup ➔ netlist reading ➔ clock definition ➔ DRC validation ➔ analysis mode transition ➔ fault modeling ➔ pattern simulation ➔ coverage statistics.

### 2. Launch Interactive Tessent Shell
```bash
tshell
```

Example session:
```tcl
tshell (SETUP)> set_context patterns -scan
tshell (SETUP)> read_verilog output/serial_adder_scan.v
tshell (SETUP)> add_clocks clk -off_state 0
tshell (SETUP)> report_clocks
tshell (SETUP)> set_system_mode analysis
tshell (ANALYSIS)> report_drc_rules t3-1
tshell (ANALYSIS)> add_faults -all
tshell (ANALYSIS)> simulate_patterns
tshell (ANALYSIS)> report_statistics
tshell (ANALYSIS)> exit
```

### 3. Run Command Strings or Dofiles
```bash
# Run inline command string
tshell -c "set_context patterns -scan; read_verilog output/serial_adder_scan.v; report_design"

# Run batch script from file
tshell -f my_script.do
```

### 4. Scan Chain Insertion Tool
Synthesize a scan-ready Verilog netlist from a circuit specification:
```bash
tshell-insertion --spec examples/serial_adder.json -o output/serial_adder_scan.v
```
This outputs:
- `output/serial_adder_scan.v`: Synthesizable Verilog netlist with stitched scan chains.
- `output/serial_adder_scan.scan.txt`: Scan connection connectivity report (`scan_in → q0 → q1 → scan_out`).

### 5. Educational Fault Simulation
Demonstrate stuck-at fault behavior (good machine vs. detected vs. masked):
```bash
tshell-scan-sim --case all
```

---

## Running Test Suite

Run the full automated test suite (35 unit tests verifying logic algebra, DRC rules, state machine transitions, and ATPG calculations):

```bash
# Using pytest
pytest -v

# Or using Python's built-in unittest runner
python3 -m unittest discover tests -v
```

---

## Golden Oracle & Manual Alignment

The manuals inform the examples; command behavior and simulation are not yet fully aligned with them:
- **`tshell_ref.pdf`**: *Tessent Shell Reference Manual* (v2026.2, Rev 43). Provides command syntax, argument structures, and DRC rule definitions.
- **`tshell_user.pdf`**: *Tessent Shell User's Manual* (v2026.2). Defines the DFT methodology, ATPG flow, and coverage metrics:
  $$\text{Fault Coverage} = \frac{\text{Detected Faults}}{\text{Total Faults}} \times 100\%$$
  $$\text{Test Coverage} = \frac{\text{Detected Faults}}{\text{Total Faults} - \text{Untestable Faults}} \times 100\%$$

For specific textbook case studies (T3, T4, T5, C1, D1), refer to [EXERCISES.md](file:///Users/phuccao/Workspace/tshell_sim_lab/EXERCISES.md).

The current implementation is an educational subset, not a substitute for Tessent or production DRC/ATPG. See [the roadmap](docs/plans/2026-11-14-tshell-roadmap.md) for known gaps and validation criteria.

---

## Repository Structure

```
tshell_sim_lab/
├── pyproject.toml              # PEP 517/621 package configuration & CLI scripts
├── requirements.txt            # Pure standard library (zero runtime dependencies)
├── requirements-dev.txt        # Development dependencies (pytest, pymupdf for offline ingestion)
├── tshell.py                   # Tessent Mock Shell CLI entrypoint
├── exercises.py                # Reference book case replay & study tool
├── insertion.py                # Scan chain insertion engine
├── scan_sim.py                 # Educational stuck-at fault simulator
├── LEGAL.md                    # Intellectual property & legal clean-room declaration
├── tessent_core/               # Core EDA simulation engine
│   ├── atpg.py                 # ATPG fault injection, simulation & statistics
│   ├── drc.py                  # DRC rule evaluation & oracle reader
│   ├── knowledge_db.json       # Pre-indexed knowledge DB (rules, excerpts, case studies)
│   ├── drc_catalog.json        # 600 catalog entries mapped to manual pages
│   ├── logic4.py               # IEEE 1164 4-state logic algebra (0, 1, X, Z)
│   ├── netlist.py              # Gate-level netlist and circuit graph model
│   └── state.py                # Tessent session FSM (SETUP <-> ANALYSIS)
├── tools/
│   └── build_knowledge_db.py   # Offline tool to rebuild knowledge_db.json from PDF
├── tests/                      # Comprehensive unit tests (37 test cases)
├── examples/                   # Sample circuit JSON specifications
└── rtl/                        # Verilog testbenches for optional hardware cross-check
```

> **Zero-Asset Policy**: Proprietary reference manuals (`*.pdf`) are **not** bundled, distributed, or accessed at runtime in this repository. All structural metadata, rule definitions, and manual excerpts are pre-indexed into `tessent_core/knowledge_db.json`. When manual revisions occur, developers can use the offline ingestion tool (`tools/build_knowledge_db.py --pdf <path>`) to update the knowledge base.

---

## Legal & Trademark Notice

See [LEGAL.md](file:///Users/phuccao/Workspace/tshell_sim_lab/LEGAL.md) for the complete legal declaration.

- **Clean-Room Independent Implementation**: All simulation models and code are original Python implementations derived from public IEEE standards and academic DFT literature.
- **Fair Use (*Google v. Oracle*)**: Command syntax and interfaces are emulated solely for educational training and workflow interoperability.
- **Trademark Notice**: Tessent™ and Siemens™ are trademarks of Siemens Industry Software Inc. This independent project is not affiliated with, endorsed by, or sponsored by Siemens.
- **License**: Educational & academic research use only under the MIT License.
