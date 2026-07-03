"""Offline contract tests for the RLS lockdown migration (Phase SEC-1A).

Reads db/migrations/004_rls_lockdown.sql as text — no database connection. Pins the
safety contract: deny-by-default RLS (no FORCE, no policies, no GRANT anywhere),
role-guarded revokes covering tables + sequences + functions, default-privilege
revokes for future objects, statement symmetry between the anon and authenticated
branches, exactly two top-level DO blocks (the apply harness must not split on ';'),
zero destructive statements, and the repo-wide assumption the lockdown relies on —
nothing in this repo uses the Supabase Data API / anon key.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SQL = (_REPO / "db" / "migrations" / "004_rls_lockdown.sql").read_text(encoding="utf-8")

_OBJECT_KINDS = ("TABLES", "SEQUENCES", "FUNCTIONS")


def _code() -> str:
    """SQL with -- comments stripped (contract applies to executable code only)."""
    return "\n".join(re.sub(r"--.*$", "", ln) for ln in _SQL.splitlines())


def test_enables_rls_on_public_tables_dynamically_owner_safe() -> None:
    code = _code()
    assert "ENABLE ROW LEVEL SECURITY" in code
    # dynamic loop over base + partitioned tables in schema public
    assert re.search(r"relkind IN \('r', 'p'\)", code)
    assert re.search(r"nspname\s*=\s*'public'", code)
    # non-owned tables must be SKIPPED (NOTICE), never abort the whole block
    assert "current_user" in code and "RAISE NOTICE" in code


def test_never_uses_force_rls() -> None:
    # FORCE would also bind the table-owner role (DATABASE_URL) and break the backend.
    assert "FORCE ROW LEVEL SECURITY" not in _code().upper()


def test_no_policies_and_no_grants_ever() -> None:
    up = _code().upper()
    assert "CREATE POLICY" not in up
    # The lockdown must only ever REVOKE. A single GRANT (even inside a DO block)
    # re-opens the P1 hole — forbid the token outright.
    assert not re.search(r"\bGRANT\b", up), "GRANT found in the lockdown migration"


def test_revokes_cover_tables_sequences_functions_and_are_guarded() -> None:
    code = _code()
    for role in ("anon", "authenticated"):
        assert re.search(rf"pg_roles WHERE rolname = '{role}'", code), f"missing existence guard for {role}"
        for kind in _OBJECT_KINDS:
            assert re.search(rf"REVOKE ALL ON ALL {kind} IN SCHEMA public FROM {role};", code), (
                f"missing REVOKE {kind} for {role}"
            )


def test_default_privileges_revoked_for_future_objects() -> None:
    code = _code()
    for role in ("anon", "authenticated"):
        for kind in _OBJECT_KINDS:
            assert re.search(
                rf"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON {kind} FROM {role};", code
            ), f"missing default-privilege revoke on {kind} for {role}"


def test_anon_and_authenticated_branches_are_symmetric() -> None:
    """The two role branches must contain byte-identical statement shapes (catches
    one-sided typos like a misspelled keyword in only one branch)."""
    code = _code()

    def branch(role: str) -> list[str]:
        m = re.search(rf"IF EXISTS \(SELECT 1 FROM pg_roles WHERE rolname = '{role}'\) THEN(.*?)END IF;", code, re.S)
        assert m, f"missing branch for {role}"
        stmts = [s.strip() for s in m.group(1).split(";") if s.strip()]
        return [re.sub(rf"\b{role}\b", "<ROLE>", s) for s in stmts]

    assert branch("anon") == branch("authenticated")


def test_service_role_untouched() -> None:
    assert "service_role" not in _code()


def test_exactly_two_top_level_do_blocks() -> None:
    # Apply contract (ACC-1B lesson): the file is executed as N whole statements, never
    # split on ';'. Exactly two DO blocks keeps the apply trivially correct.
    code = _code()
    assert len(re.findall(r"DO \$\$", code)) == 2
    assert len(re.findall(r"END \$\$;", code)) == 2
    outside = re.sub(r"DO \$\$.*?END \$\$;", "", code, flags=re.S).strip()
    assert outside == "", f"unexpected top-level SQL outside DO blocks: {outside[:120]!r}"


def test_no_destructive_statements() -> None:
    up = _code().upper()
    for token in ("DROP ", "DELETE ", "TRUNCATE", "UPDATE ", "INSERT "):
        assert token not in up, f"destructive/DML statement found: {token.strip()}"


def test_apply_preconditions_documented_in_header() -> None:
    # Both apply hazards must stay documented next to the code they protect.
    assert "Do NOT" in _SQL and "split it on ';'" in _SQL  # harness lesson
    assert "AS the DATABASE_URL / table-owner role" in _SQL  # default-privilege role coupling


def test_repo_still_has_no_supabase_data_api_usage() -> None:
    """The lockdown is safe BECAUSE nothing uses the Data API. If someone later adds
    supabase-js / supabase-py / direct PostgREST calls, this guard fails and forces a
    policy discussion instead of a silent outage."""
    pattern = re.compile(
        r"supabase-js|@supabase/|from supabase|import supabase|create_client\(|createClient\("
        r"|anon[_-]?key|supabase\.co/rest|/rest/v1/",
        re.I,
    )
    hits: list[str] = []
    # dependency manifests (any supabase client package)
    for manifest in ("apps/web/package.json", "requirements.txt", "pyproject.toml", "apps/api/pyproject.toml"):
        p = _REPO / manifest
        if p.exists() and "supabase" in p.read_text(encoding="utf-8", errors="ignore").lower():
            hits.append(manifest)
    # source trees
    for base in ("apps/web/src", "apps/api/app", "etl", "ml", "scripts"):
        for p in (_REPO / base).rglob("*"):
            if p.suffix not in {".py", ".ts", ".tsx", ".js"} or "node_modules" in str(p):
                continue
            if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p.relative_to(_REPO)))
    assert hits == [], f"Supabase Data API usage appeared — RLS policies now required: {hits}"
