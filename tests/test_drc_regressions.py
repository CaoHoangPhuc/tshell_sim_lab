from tessent_core.drc import DRCEngine
from tessent_core.netlist import CircuitGraph, Gate


def test_drc_without_scan_ports_does_not_guess_chain_or_crash():
    circuit = CircuitGraph('no_output')
    circuit.add_port('clk', 'in')
    circuit.add_port('d', 'in')
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk', 'd': 'd'}, outputs={'Q': 'q'}))
    violations = DRCEngine().run_all_checks(circuit, {'clk': 0}, [])
    assert not any(v.rule_id.startswith(('T3', 'T4', 'T5')) for v in violations)


def test_set_drc_handling_ignore_filters_out_violation():
    circuit = CircuitGraph('unreached_clock')
    circuit.add_port('clk', 'in')
    circuit.add_port('d', 'in')
    # ff has clock 'other_clk' which is not in clocks dict -> triggers C2 violation
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'other_clk', 'd': 'd'}, outputs={'Q': 'q'}))

    engine = DRCEngine()
    violations_default = engine.run_all_checks(circuit, {'clk': 0}, [])
    assert any(v.rule_id.startswith('C2') for v in violations_default)

    # Now override C2 to Ignore
    engine.handling_overrides['C2'] = 'Ignore'
    violations_ignored = engine.run_all_checks(circuit, {'clk': 0}, [])
    assert not any(v.rule_id.startswith('C2') for v in violations_ignored)


def test_c1_passes_when_clock_off_state_is_one():
    # Active-low clock: off-state is 1
    circuit = CircuitGraph('active_low_clk')
    circuit.add_port('clk_n', 'in')
    circuit.add_port('d', 'in')
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk_n', 'd': 'd'}, outputs={'Q': 'q'}))

    engine = DRCEngine()
    violations = engine.run_all_checks(circuit, clocks={'clk_n': 1}, scan_chains=[])
    assert not any(v.rule_id.startswith('C1') for v in violations)


def test_c1_fails_when_clock_is_unknown_x():
    circuit = CircuitGraph('unknown_clk')
    circuit.add_port('clk', 'in')
    circuit.add_port('floating_ctrl', 'in')
    circuit.add_port('d', 'in')
    # Clock gated with floating/unknown signal
    circuit.add_gate(Gate('g_and', 'AND', inputs={'in0': 'clk', 'in1': 'floating_ctrl'}, outputs={'out': 'gated_clk'}))
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'gated_clk', 'd': 'd'}, outputs={'Q': 'q'}))

    engine = DRCEngine()
    # When clk off-state is 1, 1 AND X is X -> triggers C1!
    violations = engine.run_all_checks(circuit, clocks={'clk': 1}, scan_chains=[])
    assert any(v.rule_id.startswith('C1') for v in violations)


def test_t3_reports_violation_when_scan_in_not_connected_to_first_cell():
    circuit = CircuitGraph('broken_scan_in')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('clk', 'in')
    circuit.add_port('other_in', 'in')
    circuit.add_port('scan_out', 'out')

    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'd': 'other_in'}, outputs={'Q': 'q1'}))
    circuit.add_gate(Gate('df2', 'DFF', inputs={'clk': 'clk', 'd': 'q1'}, outputs={'Q': 'scan_out'}))

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1', 'df2']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t3 = [v for v in violations if v.rule_id.startswith('T3')]
    assert len(t3) >= 1
    assert 'blocked' in t3[0].message.lower()


def test_t3_reports_violation_when_last_cell_not_connected_to_scan_out():
    circuit = CircuitGraph('broken_scan_out')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_out', 'out')

    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'd': 'scan_in'}, outputs={'Q': 'q1'}))
    circuit.add_gate(Gate('df2', 'DFF', inputs={'clk': 'clk', 'd': 'q1'}, outputs={'Q': 'other_out'}))

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1', 'df2']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t3 = [v for v in violations if v.rule_id.startswith('T3')]
    assert len(t3) >= 1
    assert 'blocked' in t3[0].message.lower()


def test_t3_does_not_report_violation_for_unrelated_blocked_branch():
    circuit = CircuitGraph('unrelated_branch')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_out', 'out')
    circuit.add_port('zero_net', 'in')
    circuit.add_port('unrelated_out', 'out')

    # Sensitized scan path: scan_in -> df1 -> df2 -> scan_out
    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'd': 'scan_in'}, outputs={'Q': 'q1'}))
    circuit.add_gate(Gate('df2', 'DFF', inputs={'clk': 'clk', 'd': 'q1'}, outputs={'Q': 'scan_out'}))

    # Unrelated AND gate with controlling 0
    circuit.add_gate(Gate('g_unrelated', 'AND', inputs={'in0': 'scan_in', 'in1': 'zero_net'}, outputs={'out': 'unrelated_out'}))
    circuit.set_primary_input('zero_net', 0)

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1', 'df2']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t3 = [v for v in violations if v.rule_id.startswith('T3')]
    assert len(t3) == 0


def test_t4_reports_violation_when_scan_cell_clock_not_pulsed_during_shift():
    circuit = CircuitGraph('t4_unpulsed_clock')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_out', 'out')
    circuit.add_port('dead_clk', 'in')

    # df1 is connected to dead_clk, which is not in clocks
    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'dead_clk', 'd': 'scan_in'}, outputs={'Q': 'scan_out'}))
    circuit.set_primary_input('dead_clk', 0)

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t4 = [v for v in violations if v.rule_id.startswith('T4')]
    assert len(t4) >= 1
    assert t4[0].offending_gate == 'df1'


def test_t5_reports_violation_when_reset_is_active_during_shift():
    circuit = CircuitGraph('t5_active_reset')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_out', 'out')
    circuit.add_port('active_rst', 'in')

    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'reset': 'active_rst', 'd': 'scan_in'}, outputs={'Q': 'scan_out'}))
    circuit.set_primary_input('active_rst', 1)

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t5 = [v for v in violations if v.rule_id.startswith('T5')]
    assert len(t5) >= 1
    assert t5[0].offending_gate == 'df1'


def test_d1_reports_violation_when_reset_disturbs_shift():
    circuit = CircuitGraph('d1_active_reset')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_out', 'out')
    circuit.add_port('active_rst', 'in')

    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'reset': 'active_rst', 'd': 'scan_in'}, outputs={'Q': 'scan_out'}))
    circuit.set_primary_input('active_rst', 1)

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    d1 = [v for v in violations if v.rule_id.startswith('D1')]
    assert len(d1) >= 1
    assert d1[0].offending_gate == 'df1'


def test_t3_passes_when_scan_enable_is_named_se():
    circuit = CircuitGraph('test_se')
    circuit.add_port('clk', 'in')
    circuit.add_port('se', 'in')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('scan_out', 'out')

    # Scan mux: sel=se, d0=d_func, d1=scan_in -> d_mux
    circuit.add_gate(Gate('mux1', 'IFMUX', inputs={'sel': 'se', 'd0': 'd_func', 'd1': 'scan_in'}, outputs={'out': 'd_mux'}))
    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'd': 'd_mux'}, outputs={'Q': 'scan_out'}))

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t3 = [v for v in violations if v.rule_id.startswith('T3')]
    assert len(t3) == 0


def test_t3_passes_when_cells_list_in_chain_is_arbitrarily_ordered():
    circuit = CircuitGraph('out_of_order_cells')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('scan_out', 'out')

    # True scan path: scan_in -> df0 -> df1 -> scan_out
    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'd': 'q0'}, outputs={'Q': 'scan_out'}))
    circuit.add_gate(Gate('df0', 'DFF', inputs={'clk': 'clk', 'd': 'scan_in'}, outputs={'Q': 'q0'}))

    engine = DRCEngine()
    # Cells list is [df1, df0] (declaration order where df1 is listed first)
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1', 'df0']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t3 = [v for v in violations if v.rule_id.startswith('T3')]
    assert len(t3) == 0


def test_t3_passes_when_scan_path_has_sensitized_xor():
    circuit = CircuitGraph('test_xor')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('scan_out', 'out')
    circuit.add_port('const1', 'in')

    # XOR with const1 = 1 (inversion): sensitized
    circuit.add_gate(Gate('g_xor', 'XOR', inputs={'in0': 'scan_in', 'in1': 'const1'}, outputs={'out': 'd_xor'}))
    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'd': 'd_xor'}, outputs={'Q': 'scan_out'}))
    circuit.set_primary_input('const1', 1)

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t3 = [v for v in violations if v.rule_id.startswith('T3')]
    assert len(t3) == 0


def test_t3_fails_when_scan_path_xor_is_unsensitized():
    circuit = CircuitGraph('test_xor_x')
    circuit.add_port('clk', 'in')
    circuit.add_port('scan_in', 'in')
    circuit.add_port('scan_out', 'out')
    circuit.add_port('floating_ctrl', 'in')

    # XOR with floating_ctrl = X: unsensitized
    circuit.add_gate(Gate('g_xor', 'XOR', inputs={'in0': 'scan_in', 'in1': 'floating_ctrl'}, outputs={'out': 'd_xor'}))
    circuit.add_gate(Gate('df1', 'DFF', inputs={'clk': 'clk', 'd': 'd_xor'}, outputs={'Q': 'scan_out'}))

    engine = DRCEngine()
    chains = [{'name': 'chain1', 'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['df1']}]
    violations = engine.run_all_checks(circuit, clocks={'clk': 0}, scan_chains=chains)
    t3 = [v for v in violations if v.rule_id.startswith('T3')]
    assert len(t3) >= 1
    assert t3[0].offending_gate == 'g_xor'
