// Educational generic scan insertion; not a technology-mapped netlist.
module serial_adder_scan(clk, reset, a, b, scan_en, scan_in, sum, scan_out);
  input clk, reset, a, b, scan_en, scan_in;
  output sum, scan_out;
  reg q0, q1;

  always @(posedge clk) begin
    if (reset) begin
      q0 <= 1'b0;
      q1 <= 1'b0;
    end else if (scan_en) begin
      q0 <= scan_in;
      q1 <= q0;
    end else begin
      q0 <= (a ^ q1);
      q1 <= (q0 & b);
    end
  end

  assign sum = (q0 ^ q1);
  assign scan_out = q1;
endmodule
