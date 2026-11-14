# Legal Notice, Intellectual Property & Clean-Room Declaration

This document sets forth the intellectual property policy, clean-room implementation status, and legal compliance framework of the **`tshell_sim_lab`** project.

---

## 1. Clean-Room Implementation & Independent Creation

All source code, logic models, test fixtures, parsers, and data structures contained within this repository are **100% original, independent creations** authored purely in Python. 

- **No Proprietary Code**: This project contains zero decompiled, disassembled, reverse-engineered, or copied binary or source code from Siemens Industry Software Inc. (or Mentor Graphics Corporation).
- **Fundamental EDA Principles**: All circuit modeling, scan chain stitching, fault injection, and logic simulation algorithms are derived from publicly accessible, standard academic literature (e.g., IEEE 1164 four-state logic, Poage's 1963 stuck-at fault model, and classical scan-based DFT principles).

---

## 2. Non-Infringement of Copyright

### A. Idea vs. Expression Dichotomy (17 U.S.C. § 102(b) & International Law)
Under **17 U.S.C. § 102(b)**, the **Berne Convention**, and national intellectual property laws:
> *"In no case does copyright protection for an original work of authorship extend to any idea, procedure, process, system, method of operation, concept, principle, or discovery, regardless of the form in which it is described, explained, illustrated, or embodied in such work."*

The functional concepts of Design-for-Testability (DFT), scan chain tracing, clock off-state verification, and ATPG test coverage calculations are uncopyrightable systems and methods of operation. This repository merely implements an educational model of these functional concepts.

### B. Command Syntax & Interoperability (*Google LLC v. Oracle America, Inc.*)
In *Google LLC v. Oracle America, Inc.*, 141 S. Ct. 1164 (2021), the Supreme Court of the United States reaffirmed that the reimplementation of functional declaring code, command names, and syntactic interfaces to enable interoperability, training, and developer reuse constitutes **Fair Use as a matter of law**. 

The commands emulated in `tshell.py` (such as `set_context`, `read_verilog`, `add_clocks`, `set_system_mode`) represent functional interfaces necessary to simulate standard industry EDA workflows for learning purposes.

### C. Educational Fair Use (17 U.S.C. § 107)
This project satisfies all four statutory fair use factors under **17 U.S.C. § 107**:
1. **Purpose and Character of the Use**: Non-profit, non-commercial, transformative, and strictly educational.
2. **Nature of the Copyrighted Work**: Factual, functional reference material describing tool operation.
3. **Amount and Substantiality Used**: No creative prose, proprietary graphics, or documentation manuals are distributed. Only functional rule IDs (e.g., `C1`, `T3`) and bibliographic page citations are referenced.
4. **Effect on the Market**: This educational simulator poses zero market harm to Siemens. It cannot replace Tessent™ licenses, does not support commercial cell libraries or multi-million gate ASICs, and rather serves to educate aspiring hardware and test engineers in DFT fundamentals.

---

## 3. Zero-Asset Policy (No Redistribution of Proprietary Materials)

This repository strictly enforces a **Zero-Asset Policy**:
- **NO PDF Manuals**: The reference manuals (`tshell_ref.pdf`, `tshell_user.pdf`) are explicitly excluded via `.gitignore` and are not distributed or hosted on this repository.
- **NO Cell Libraries**: No proprietary foundry or commercial standard cell libraries (e.g., TSMC, Samsung, Nangate, Synopsys) are packaged or required.
- **Generic Benchmarks**: All Verilog modules and circuit graph representations represent generic academic circuits (e.g., serial adder toy circuit).

---

## 4. Nominative Fair Use of Trademarks

- **Tessent™** and **Siemens™** are registered trademarks of Siemens Industry Software Inc. (or its parent/affiliate companies).
- Any use of the word "Tessent" in this repository is strictly for **Nominative Fair Use** (under *New Kids on the Block v. News America Publishing, Inc.*, 971 F.2d 302 (9th Cir. 1992)) to accurately describe and identify the command language syntax being modeled.
- **No Affiliation**: This project is completely independent. It is **NOT** affiliated with, endorsed by, sponsored by, or associated in any way with Siemens Industry Software Inc.

---

## 5. Disclaimer of Warranty

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE.
