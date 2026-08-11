from pathlib import Path


def test_nullable_sql_parameters_have_explicit_types():
    routes = Path("app/routes")
    assert not [path for path in routes.glob("*.py") if "%s IS NULL" in path.read_text()]
