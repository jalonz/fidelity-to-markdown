import re
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from fidelity_csv_to_markdown import CONTRACT, Contract, DropRow, Total


def test_mistyped_field_fails_loudly():
    # A typo'd field must raise, not silently fall back to a default.
    fields = asdict(CONTRACT)
    fields["heading_templat"] = fields.pop("heading_template")
    with pytest.raises(TypeError, match="heading_templat"):
        Contract(**fields)


def test_invalid_drop_rows_regex_fails_at_construction():
    with pytest.raises(re.error):
        replace(CONTRACT, drop_rows=(DropRow(column="Account Number", regex="([unclosed"),))


def test_invalid_as_of_pattern_fails_at_construction():
    with pytest.raises(re.error):
        replace(CONTRACT, as_of_pattern="(?P<bad")


def test_contract_is_immutable():
    with pytest.raises(FrozenInstanceError):
        CONTRACT.heading_template = "{Symbol}"


@pytest.mark.parametrize("field, value", [
    ("drop_columns", ("Sector")),             # missing comma: a str, not a tuple
    ("footer_markers", ("fidelity.com")),
    ("portfolio_totals", (Total(label="X", column="Current value"))),
    ("summary_header", "yes"),
    ("column_aliases", [("a", "b")]),
    ("as_of_pattern", 123),
])
def test_wrong_typed_field_fails_at_construction(field, value):
    with pytest.raises(TypeError, match=f"Contract.{field}"):
        replace(CONTRACT, **{field: value})


def test_wrong_typed_nested_field_fails_at_construction():
    with pytest.raises(TypeError, match="Total.column"):
        Total(label="X", column=None)


def test_as_of_pattern_none_allowed():
    assert replace(CONTRACT, as_of_pattern=None).as_of_pattern is None
