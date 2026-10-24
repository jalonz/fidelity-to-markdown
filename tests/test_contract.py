import re
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from fidelity_csv_to_markdown import CONTRACT, Contract, DropRow


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
        CONTRACT.group_by = "Symbol"
