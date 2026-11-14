`timescale 1ns/1ps

// Independent RTL observations for the document-based scan exercises.
// This is a small simulation, not a Tessent design-rule checker.
module tb_document_cases;
  `include "procedure.vh"

  reg clk = 0;
  reg reset = 0;
  reg scan_en = 0;
  reg scan_in = 0;
  wire scan_out;
  reg shift_active = 0;
  reg expected_q0 = 0;
  reg expected_q1 = 0;
  integer cycle;
  integer observed_edges = 0;
  integer mismatches = 0;
  integer reset_issues = 0;
  integer clock_issues = 0;

  scan_chain dut (
    .clk(clk), .reset(reset), .scan_en(scan_en),
    .scan_in(scan_in), .scan_out(scan_out)
  );

  // Count actual, binary rising edges reaching the sequential cells, rather
  // than assuming that a requested pulse was applied.
  always @(posedge clk) begin
    if (shift_active && clk === 1'b1)
      observed_edges = observed_edges + 1;
  end

  initial begin
    $display("LAB simulation: two-flop serial shift (not Tessent DRC)");

    // Establish a known state outside the shift procedure.
    reset = 1;
    #2 clk = 1;
    #1 clk = 0;
    #1 reset = 0;
    #1;
    shift_active = 1;
    scan_en = SCAN_ENABLE;
    reset = SHIFT_RESET;

    for (cycle = 0; cycle < 4; cycle = cycle + 1) begin
      // The non-uniform input exercises both stages of the serial path.
      case (cycle)
        0: scan_in = 1;
        1: scan_in = 0;
        2: scan_in = 1;
        default: scan_in = 0;
      endcase
      #1;
      if (reset !== 1'b0) begin
        $display("LAB observation: cycle=%0d reset during shift expected=0 actual=%b", cycle, reset);
        reset_issues = reset_issues + 1;
      end
      expected_q1 = expected_q0;
      expected_q0 = scan_in;

      if (SHIFT_CLOCK === 1'b1)
        clk = 1;
      else if (SHIFT_CLOCK === 1'b0)
        clk = 0;
      else begin
        clk = 1'bx;
        clock_issues = clock_issues + 1;
        $display("LAB observation: cycle=%0d shift clock is unknown", cycle);
      end
      #1;
      $display("LAB trace: cycle=%0d si=%b se=%b clk=%b reset=%b so=%b expected_so=%b rising_edges=%0d",
               cycle, scan_in, scan_en, clk, reset, scan_out, expected_q1, observed_edges);
      if (scan_out !== expected_q1) begin
        $display("LAB observation: cycle=%0d serial output differs: expected=%b actual=%b",
                 cycle, expected_q1, scan_out);
        mismatches = mismatches + 1;
      end
      #1 clk = 0;
      #1;
    end
    shift_active = 0;
    if (observed_edges == 0) begin
      $display("LAB observation: no binary rising edge reached the flip-flops during shift");
      clock_issues = clock_issues + 1;
    end
    if (mismatches || reset_issues || clock_issues) begin
      $display("LAB simulation: issues observed (serial=%0d reset=%0d clock=%0d)",
               mismatches, reset_issues, clock_issues);
      $fatal(1);
    end
    $display("LAB simulation: serial data, shift clock and reset observations completed without mismatch");
    $finish;
  end
endmodule
