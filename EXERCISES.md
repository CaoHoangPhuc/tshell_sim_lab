# Reference manual case studies

The exercises index five illustrative cases from the Tessent Shell Reference Manual 2026.2 Rev 43. Page numbers refer to PDF pages. These are study examples, not DRC results for the current design.

| Case | Rule | PDF pages |
| --- | --- | --- |
| `case01` | T3 | 4522–4524 |
| `case02` | T4 | 4525–4528 |
| `case03` | T5 | 4529–4531 |
| `case04` | C1 | 3809–3814 |
| `case05` | D1 | 3863–3866 |

List cases and create a study directory:

```sh
tshell-exercises list
tshell-exercises init case01 --dir work/case01-study-1
```

To read or replay material, supply your own authorized reference PDF and install PyMuPDF (`pip install pymupdf`). The file is read locally and is not copied into the package:

```sh
tshell-exercises run --dir work/case01-study-1 --pdf /path/to/tshell_ref.pdf
tshell-exercises source --dir work/case01-study-1 --page 4522 --pdf /path/to/tshell_ref.pdf
tshell-exercises commands --dir work/case01-study-1 --pdf /path/to/tshell_ref.pdf
```

Alternatively set `TSHELL_REFERENCE_PDF` to the PDF path and omit `--pdf`. The command walkthrough is currently available for `case01`. Page and excerpt extraction is tied to the specified manual revision; another edition can have different pagination or text.

Older standalone RTL exercises can still be run with `tshell-exercises run --dir <exercise-directory>`. They require Icarus Verilog (`iverilog` and `vvp`) and execute local Verilog testbenches; only run designs and testbenches you trust.
