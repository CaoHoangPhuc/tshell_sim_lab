`timescale 1ns/1ps

// Checks Verilog emitted by the insertion example against independent equations.
module tb_scan_demo;
  reg clk = 0;
  reg reset = 0;
  reg scan_en = 0;
  reg scan_in = 0;
  reg a = 0;
  reg b = 0;
  wire sum;
  wire scan_out;
  reg ref_q0;
  reg ref_q1;
  reg next_q0;
  reg next_q1;
  integer initial_state;
  integer inputs;
  integer checks = 0;

  serial_adder_scan dut (
    .clk(clk), .reset(reset), .a(a), .b(b), .scan_en(scan_en),
    .scan_in(scan_in), .sum(sum), .scan_out(scan_out)
  );

  task tick;
    begin
      #5 clk = 1;
      #1;
      #4 clk = 0;
      #1;
    end
  endtask

  task check_outputs;
    input [255:0] label_text;
    begin
      checks = checks + 1;
      if (scan_out !== ref_q1 || sum !== (ref_q0 ^ ref_q1)) begin
        $display("FAIL %0s: expected scan_out=%b sum=%b, got %b %b at %0t",
                 label_text, ref_q1, ref_q0 ^ ref_q1, scan_out, sum, $time);
        $fatal(1);
      end
    end
  endtask

  task shift_bit;
    input bit_in;
    begin
      scan_en = 1;
      scan_in = bit_in;
      next_q1 = ref_q0;
      next_q0 = bit_in;
      tick;
      ref_q0 = next_q0;
      ref_q1 = next_q1;
      check_outputs("scan shift");
    end
  endtask

  initial begin
    // Reset dominates scan enable and initializes both scan cells.
    reset = 1; scan_en = 1; scan_in = 1;
    tick;
    ref_q0 = 0; ref_q1 = 0;
    check_outputs("reset during scan");
    reset = 0;

    // Test all four preloaded states against all input combinations.
    for (initial_state = 0; initial_state < 4; initial_state = initial_state + 1) begin
      for (inputs = 0; inputs < 4; inputs = inputs + 1) begin
        // Two shifts load q1 first, then q0, regardless of prior state.
        shift_bit((initial_state >> 1) & 1);
        shift_bit(initial_state & 1);
        if ({ref_q1, ref_q0} !== initial_state[1:0]) $fatal(1, "bad test preload");
        a = (inputs >> 1) & 1;
        b = inputs & 1;
        scan_en = 0;
        next_q0 = a ^ ref_q1;
        next_q1 = ref_q0 & b;
        tick;
        ref_q0 = next_q0;
        ref_q1 = next_q1;
        check_outputs("functional capture");
        // Scan out q1 immediately, then q0 after one shift; checking sum
        // as well makes the serial ordering observable at each clock edge.
        shift_bit(0);
        shift_bit(1);
      end
    end
    $display("PASS: reset, 16 state/input captures and scan shift (%0d checks)", checks);
    $finish;
  end
endmodule
