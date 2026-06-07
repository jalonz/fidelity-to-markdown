import copy

from fidelity_csv_to_markdown import validate_contract


def test_shipped_contract_is_valid(contract):
    # The contract that ships with the script must pass its own schema check.
    assert validate_contract(contract) == []


def test_non_mapping_rejected():
    errors = validate_contract([])
    assert errors and "top level must be a mapping" in errors[0]


def test_missing_version_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["contract"].pop("version")
    errors = validate_contract(bad)
    assert any("contract.version" in e for e in errors)


def test_unknown_top_level_key_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["inputt_cleanup"] = {}  # typo of input_cleanup
    errors = validate_contract(bad)
    assert any("unknown key 'inputt_cleanup'" in e for e in errors)


def test_unknown_key_in_summary_header_rejected(contract):
    bad = copy.deepcopy(contract)
    # Typo of "enabled" — would otherwise silently fall back to default (off).
    bad["output"]["markdown"]["summary_header"]["enabld"] = True
    errors = validate_contract(bad)
    assert any("summary_header: unknown key 'enabld'" in e for e in errors)


def test_heading_template_typo_rejected(contract):
    bad = copy.deepcopy(contract)
    sections = bad["output"]["markdown"]["sections"]
    sections["heading-template"] = sections.pop("heading_template")
    errors = validate_contract(bad)
    assert any("sections: unknown key 'heading-template'" in e for e in errors)


def test_wrong_type_enabled_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["output"]["markdown"]["summary_header"]["enabled"] = "yes"
    errors = validate_contract(bad)
    assert any("summary_header.enabled: must be a boolean" in e for e in errors)


def test_totals_entry_missing_column_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["output"]["markdown"]["summary_header"]["totals"] = [{"label": "X"}]
    errors = validate_contract(bad)
    assert any("totals[0].column: required" in e for e in errors)


def test_invalid_regex_in_drop_rows_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["input_cleanup"]["drop_rows"][0]["regex"] = "([unclosed"
    errors = validate_contract(bad)
    assert any("drop_rows[0].regex: invalid regex" in e for e in errors)


def test_invalid_as_of_pattern_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["output"]["markdown"]["summary_header"]["as_of"]["pattern"] = "(?P<bad"
    errors = validate_contract(bad)
    assert any("as_of.pattern: invalid regex" in e for e in errors)


def test_input_cleanup_wrong_type_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["input_cleanup"] = ["not", "a", "mapping"]
    errors = validate_contract(bad)
    assert any("input_cleanup: must be a mapping" in e for e in errors)


def test_unknown_key_under_output_markdown_rejected(contract):
    bad = copy.deepcopy(contract)
    bad["output"]["markdown"]["sektion_header"] = {"enabled": True}
    errors = validate_contract(bad)
    assert any("output.markdown: unknown key 'sektion_header'" in e for e in errors)


def test_descriptive_metadata_not_policed(contract):
    # Unknown keys inside descriptive blocks are harmless and must not abort.
    ok = copy.deepcopy(contract)
    ok["task"] = "anything"
    ok["input"]["some_future_descriptive_key"] = "tolerated"
    assert validate_contract(ok) == []
