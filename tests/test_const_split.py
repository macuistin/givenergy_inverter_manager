"""const.py is split by kind, and every name that existed before the split is still importable."""

import ast
import json

import pytest

from custom_components.givenergy_inverter_manager import conf, const, defaults, tuning
from tests.helpers import PKG, ROOT

_NAMES = json.loads((ROOT / "tests" / "fixtures" / "const_names.json").read_text())


@pytest.mark.parametrize("name", _NAMES)
def test_every_name_from_before_the_split_is_still_in_const(name):
    assert hasattr(const, name)


@pytest.mark.parametrize("module", [conf, defaults, tuning], ids=lambda m: m.__name__)
def test_const_re_exports_the_split_modules_by_identity(module):
    names = [n for n in vars(module) if n.isupper()]

    assert names
    assert all(getattr(const, n) is getattr(module, n) for n in names)


@pytest.mark.parametrize("stem", ["conf", "defaults", "tuning"])
def test_split_modules_import_nothing_so_they_cannot_form_a_cycle(stem):
    tree = ast.parse((PKG / f"{stem}.py").read_text(encoding="utf-8"))

    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]


def test_each_split_module_holds_only_its_own_kind():
    assert all(n.startswith("CONF_") for n in vars(conf) if n.isupper())
    assert all(n.startswith("DEFAULT_") for n in vars(defaults) if n.isupper())
    assert not [n for n in vars(tuning) if n.startswith(("CONF_", "DEFAULT_"))]
