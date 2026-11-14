#!/bin/sh
# Build and run this educational example without a host Icarus installation.
set -eu
lab_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image=tshell-sim-lab-rtl:local

docker build -t "$image" -f "$lab_dir/rtl/Dockerfile" "$lab_dir/rtl"
docker run --rm --network none -v "$lab_dir:/lab:ro" -w /lab "$image" sh -eu -c '
  python3 insertion.py --spec examples/serial_adder.json -o /tmp/serial_adder_scan.v
  iverilog -g2012 -s tb_scan_demo -o /tmp/tshell_scan_tb \
    rtl/tb_scan_demo.v /tmp/serial_adder_scan.v
  vvp /tmp/tshell_scan_tb
'
