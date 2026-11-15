from tessent_core.state import SessionFSM


def test_non_scan_flop_is_excluded_from_inferred_scan_chain(tmp_path):
    design = tmp_path / "mixed.v"
    design.write_text("""
module mixed(clk, reset, scan_en, scan_in, scan_out, d);
  input clk, reset, scan_en, scan_in, d;
  output scan_out;
  reg scan_q, functional_q;
  assign scan_out = scan_q;
  always @(posedge clk) begin
    if (reset) scan_q <= 1'b0;
    else if (scan_en) scan_q <= scan_in;
    else scan_q <= d;
  end
  always @(posedge clk) begin
    if (reset) functional_q <= 1'b0;
    else functional_q <= d;
  end
endmodule
""", encoding="utf-8")

    session = SessionFSM()
    loaded, _ = session.load_verilog(design)
    assert loaded
    session.add_clock("clk", 0)

    assert not any(v.rule_id.startswith("T3") for v in session.run_drc())
    assert session.scan_chains[0]["cells"] == ["dff_scan_q"]
