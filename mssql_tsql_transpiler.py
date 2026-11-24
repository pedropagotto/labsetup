#!/usr/bin/env python3
"""
Transpilador determinístico de T-SQL (Azure SQL / SQL Server) para PostgreSQL / PL/pgSQL.
Cobre expressões comuns, Views, Functions, Stored Procedures e Triggers,
com marcação inline '-- TODO: [REVISAR]' para construções complexas.
"""

from dataclasses import dataclass, field
import re

import mssql_to_pg_ddl


@dataclass
class RoutineDef:
    kind: str  # "VIEW", "FUNCTION", "PROCEDURE", "TRIGGER"
    schema: str
    name: str
    definition: str
    parent_schema: str = None
    parent_table: str = None
    trigger_timing: str = None  # "AFTER" or "INSTEAD OF"
    trigger_events: list = field(default_factory=list)  # ["INSERT", "UPDATE", "DELETE"]


COMPLEX_CONSTRUCT_RULES = (
    (r"(?is)\bDECLARE\s+\S+\s+CURSOR\b", "Uso de CURSOR detectado (reescrever com FOR ... IN ... LOOP no PL/pgSQL)."),
    (r"(?is)\bEXEC(?:UTE)?\s*\(", "SQL dinâmico EXEC(...) detectado (usar EXECUTE ... USING no PL/pgSQL)."),
    (r"(?is)\bMERGE\s+INTO\b|\bMERGE\s+\[", "Comando MERGE detectado (validar sintaxe MERGE do PostgreSQL 15+ ou usar ON CONFLICT)."),
    (r"(?is)(?:INTO|TABLE)\s+#[a-zA-Z_][a-zA-Z0-9_]*", "Tabela temporária '#...' detectada (usar CREATE TEMP TABLE ... ON COMMIT DROP)."),
    (r"(?is)\b(?:CROSS|OUTER)\s+APPLY\b", "CROSS/OUTER APPLY detectado (converter para JOIN LATERAL)."),
    (r"(?is)\bOPENJSON\b", "Função OPENJSON detectada (converter para jsonb_to_recordset / jsonb_array_elements)."),
    (r"(?is)\b(?:PIVOT|UNPIVOT)\b", "Operador PIVOT/UNPIVOT detectado (reescrever com CASE/crosstab)."),
)


def detect_complex_constructs(tsql):
    """Detecta construções T-SQL que exigem revisão manual no PostgreSQL."""
    warnings = []
    for pattern, message in COMPLEX_CONSTRUCT_RULES:
        if re.search(pattern, tsql or ""):
            warnings.append(message)
    return warnings


def _replace_brackets(text, naming="lowercase"):
    """Converte identificadores [schema].[obj] e [col] para PostgreSQL."""
    def _repl_qualified(match):
        sch = match.group(1)
        obj = match.group(2)
        return mssql_to_pg_ddl.format_qualified_table(sch, obj, naming=naming)

    out = re.sub(r"\[([^\]]+)\]\s*\.\s*\[([^\]]+)\]", _repl_qualified, text)
    out = re.sub(r"\[([^\]]+)\]", lambda m: mssql_to_pg_ddl.format_identifier(m.group(1), naming=naming), out)
    # Converte dbo.qualquer_coisa sem colchetes para public.qualquer_coisa
    out = re.sub(r"(?i)\bdbo\.([a-zA-Z_][a-zA-Z0-9_]*)", lambda m: f"public.{mssql_to_pg_ddl.format_identifier(m.group(1), naming=naming)}", out)
    return out


def _convert_dateadd(text):
    """Converte DATEADD(part, n, date) para aritmética de INTERVAL do PostgreSQL."""
    unit_map = {
        "yy": "year", "yyyy": "year", "year": "year",
        "mm": "month", "m": "month", "month": "month",
        "dd": "day", "d": "day", "day": "day",
        "hh": "hour", "hour": "hour",
        "mi": "minute", "n": "minute", "minute": "minute",
        "ss": "second", "s": "second", "second": "second",
    }

    def _repl(m):
        raw_part = m.group(1).strip().lower()
        n_expr = m.group(2).strip()
        dt_expr = m.group(3).strip()
        pg_unit = unit_map.get(raw_part, raw_part)
        return f"({dt_expr}::TIMESTAMP + ({n_expr}) * INTERVAL '1 {pg_unit}')"

    return re.sub(
        r"(?is)\bDATEADD\s*\(\s*([a-zA-Z]+)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
        _repl,
        text,
    )


def _convert_top_to_limit(text):
    """Converte SELECT [DISTINCT] TOP N ... para SELECT [DISTINCT] ... LIMIT N em queries simples."""
    pattern = re.compile(
        r"(?is)\bSELECT\s+(DISTINCT\s+)?TOP\s*\(?\s*(\d+)\s*\)?\s+(.*?)(?=(?:;|\bUNION\b|\bEXCEPT\b|\bINTERSECT\b|$))"
    )

    def _repl(m):
        distinct = m.group(1) or ""
        top_n = m.group(2)
        body = m.group(3).rstrip()
        if re.search(r"(?is)\bLIMIT\s+\d+\b", body):
            return f"SELECT {distinct}{body}"
        return f"SELECT {distinct}{body} LIMIT {top_n}"

    return pattern.sub(_repl, text)


def transpile_tsql_expressions(sql_text, naming="lowercase"):
    """Converte expressões, funções e sintaxe T-SQL comuns para PostgreSQL."""
    out = sql_text or ""

    # Remove table hints como WITH (NOLOCK)
    out = re.sub(r"(?is)\bWITH\s*\(\s*(?:NOLOCK|READPAST|UPDLOCK|ROWLOCK|HOLDLOCK)(?:\s*,\s*(?:NOLOCK|READPAST|UPDLOCK|ROWLOCK|HOLDLOCK))*\s*\)", "", out)

    # Identificadores entre colchetes e prefixo dbo.
    out = _replace_brackets(out, naming=naming)

    # Literais Unicode N'...'
    out = re.sub(r"\bN'", "'", out)

    # Funções simples 1:1
    out = re.sub(r"(?is)\bISNULL\s*\(", "COALESCE(", out)
    out = re.sub(r"(?is)\bGETDATE\s*\(\s*\)", "CURRENT_TIMESTAMP", out)
    out = re.sub(r"(?is)\bSYSDATETIME\s*\(\s*\)", "CURRENT_TIMESTAMP", out)
    out = re.sub(r"(?is)\bSYSDATETIMEOFFSET\s*\(\s*\)", "CURRENT_TIMESTAMP", out)
    out = re.sub(r"(?is)\bGETUTCDATE\s*\(\s*\)", "(NOW() AT TIME ZONE 'UTC')", out)
    out = re.sub(r"(?is)\bSYSUTCDATETIME\s*\(\s*\)", "(NOW() AT TIME ZONE 'UTC')", out)
    out = re.sub(r"(?is)\bNEWID\s*\(\s*\)", "gen_random_uuid()", out)
    out = re.sub(r"(?is)\bNEWSEQUENTIALID\s*\(\s*\)", "gen_random_uuid()", out)
    out = re.sub(r"(?is)\bLEN\s*\(", "LENGTH(", out)
    out = re.sub(r"(?is)\bSCOPE_IDENTITY\s*\(\s*\)", "LASTVAL()", out)

    # CHARINDEX(sub, str) -> STRPOS(str, sub)
    out = re.sub(
        r"(?is)\bCHARINDEX\s*\(\s*([^,()]+)\s*,\s*([^()]+)\s*\)",
        r"STRPOS(\2, \1)",
        out,
    )

    # IIF(cond, a, b) -> CASE WHEN cond THEN a ELSE b END
    out = re.sub(
        r"(?is)\bIIF\s*\(\s*([^,()]+)\s*,\s*([^,()]+)\s*,\s*([^()]+)\s*\)",
        r"CASE WHEN \1 THEN \2 ELSE \3 END",
        out,
    )

    # DATEADD
    out = _convert_dateadd(out)

    # TOP N -> LIMIT N
    out = _convert_top_to_limit(out)

    return out.strip()


def _map_param_type(raw_type):
    """Mapeia tipo T-SQL de parâmetro/retorno para PostgreSQL."""
    m = re.match(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\(([^)]+)\))?", raw_type.strip())
    if not m:
        return "TEXT"
    dtype = m.group(1)
    params = m.group(2)
    max_len, prec, scale = None, None, None
    if params:
        parts = [p.strip() for p in params.split(",")]
        if dtype.lower() in ("decimal", "numeric"):
            prec = int(parts[0]) if parts[0].isdigit() else None
            scale = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        else:
            max_len = -1 if parts[0].lower() == "max" else (int(parts[0]) if parts[0].isdigit() else None)
    pg_type, _ = mssql_to_pg_ddl.map_tsql_type(dtype, max_length=max_len, precision=prec, scale=scale)
    return pg_type


def _parse_tsql_params(raw_params, naming="lowercase"):
    """Converte lista de parâmetros T-SQL (@p1 INT = 0 OUTPUT) para assinatura PostgreSQL."""
    if not raw_params or not raw_params.strip():
        return [], {}
    params_out = []
    name_map = {}
    for item in mssql_to_pg_ddl._split_top_level_commas(raw_params):
        cleaned = re.sub(r"(?is)\bREADONLY\b", "", item).strip()
        is_out = bool(re.search(r"(?is)\b(?:OUT|OUTPUT)\b", cleaned))
        cleaned = re.sub(r"(?is)\b(?:OUT|OUTPUT)\b", "", cleaned).strip()

        default_val = None
        if "=" in cleaned:
            left, right = cleaned.split("=", 1)
            cleaned = left.strip()
            default_val = transpile_tsql_expressions(right.strip(), naming=naming)

        m = re.match(r"^@([a-zA-Z_][a-zA-Z0-9_]*)\s+(.+)$", cleaned)
        if not m:
            continue
        orig_name = m.group(1)
        pg_name = f"p_{mssql_to_pg_ddl.format_identifier(orig_name, naming=naming)}"
        pg_type = _map_param_type(m.group(2))
        name_map[f"@{orig_name}"] = pg_name

        mode = "INOUT " if is_out else ""
        sig = f"{mode}{pg_name} {pg_type}"
        if default_val is not None:
            sig += f" DEFAULT {default_val}"
        params_out.append(sig)
    return params_out, name_map


def convert_view_to_pg(routine, naming="lowercase"):
    """Converte uma VIEW T-SQL para CREATE OR REPLACE VIEW no PostgreSQL."""
    q_name = mssql_to_pg_ddl.format_qualified_table(routine.schema, routine.name, naming=naming)
    warnings = [f"VIEW {q_name}: {w}" for w in detect_complex_constructs(routine.definition)]

    m = re.search(
        r"(?is)\bCREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+[^\s(]+(?:\s*\(([^)]+)\))?(?:\s+WITH\s+[^A]+)?\s+AS\s+(.*)$",
        routine.definition.strip(),
    )
    if m:
        col_list = m.group(1)
        select_body = m.group(2).strip().rstrip(";")
    else:
        col_list = None
        select_body = routine.definition.strip().rstrip(";")

    pg_body = transpile_tsql_expressions(select_body, naming=naming)
    cols_clause = ""
    if col_list:
        cols = [mssql_to_pg_ddl.format_identifier(c, naming=naming) for c in col_list.split(",")]
        cols_clause = f" ({', '.join(cols)})"

    todo_prefix = "".join(f"-- TODO: [REVISAR] {w}\n" for w in warnings)
    sql = f"{todo_prefix}CREATE OR REPLACE VIEW {q_name}{cols_clause} AS\n{pg_body};"
    return sql, warnings


def convert_function_to_pg(routine, naming="lowercase"):
    """Converte uma FUNCTION (escalar ou table-valued) T-SQL para PostgreSQL."""
    q_name = mssql_to_pg_ddl.format_qualified_table(routine.schema, routine.name, naming=naming)
    warnings = [f"FUNCTION {q_name}: {w}" for w in detect_complex_constructs(routine.definition)]

    header_m = re.search(
        r"(?is)\bCREATE\s+(?:OR\s+ALTER\s+)?FUNCTION\s+[^\s(]+\s*\((.*?)\)\s*RETURNS\s+(TABLE\s*\([^)]*\)|TABLE|[^\s]+(?:\s*\([^)]+\))?)\s+(?:WITH\s+.*?\s+)?AS\s+(.*)$",
        routine.definition.strip(),
    )
    if not header_m:
        warnings.append(f"FUNCTION {q_name}: assinatura não reconhecida automaticamente (revisar manualmente).")
        commented = "\n".join(f"-- {line}" for line in routine.definition.splitlines())
        return f"-- TODO: [REVISAR] FUNCTION {q_name}\n{commented}", warnings

    raw_params, raw_ret, raw_body = header_m.group(1), header_m.group(2).strip(), header_m.group(3).strip()
    params_list, name_map = _parse_tsql_params(raw_params, naming=naming)

    if raw_ret.upper().startswith("TABLE"):
        ret_inner = re.search(r"(?is)^TABLE\s*\((.*)\)$", raw_ret)
        if ret_inner:
            cols = []
            for c_def in mssql_to_pg_ddl._split_top_level_commas(ret_inner.group(1)):
                cm = re.match(r"^\s*(\[[^\]]+\]|\"[^\"]+\"|\S+)\s+(.+)$", c_def.strip())
                if cm:
                    c_name = mssql_to_pg_ddl.format_identifier(cm.group(1), naming=naming)
                    c_type = _map_param_type(cm.group(2))
                    cols.append(f"{c_name} {c_type}")
            pg_ret = f"TABLE ({', '.join(cols)})"
        else:
            pg_ret = "SETOF RECORD"
            warnings.append(f"FUNCTION {q_name}: Inline Table-Valued Function convertida para SETOF RECORD (especifique RETURNS TABLE (...)).")
    else:
        pg_ret = _map_param_type(raw_ret)

    body = raw_body.rstrip(";")
    body = re.sub(r"(?is)^\s*BEGIN\b", "", body)
    body = re.sub(r"(?is)\bEND\s*$", "", body).strip()

    for old_p, new_p in sorted(name_map.items(), key=lambda x: len(x[0]), reverse=True):
        body = re.sub(rf"(?<![a-zA-Z0-9_]){re.escape(old_p)}\b", new_p, body, flags=re.IGNORECASE)

    # Inline RETURN (SELECT ...)
    inline_ret = re.match(r"(?is)^RETURN\s*\(\s*(SELECT\b.*)\s*\)$", body)
    if inline_ret:
        pg_select = transpile_tsql_expressions(inline_ret.group(1), naming=naming)
        todo_prefix = "".join(f"-- TODO: [REVISAR] {w}\n" for w in warnings)
        sql = (
            f"{todo_prefix}CREATE OR REPLACE FUNCTION {q_name}({', '.join(params_list)})\n"
            f"RETURNS {pg_ret}\n"
            f"LANGUAGE sql\n"
            f"AS $$\n{pg_select};\n$$;"
        )
        return sql, warnings

    pg_body = transpile_tsql_expressions(body, naming=naming)
    todo_prefix = "".join(f"-- TODO: [REVISAR] {w}\n" for w in warnings)
    sql = (
        f"{todo_prefix}CREATE OR REPLACE FUNCTION {q_name}({', '.join(params_list)})\n"
        f"RETURNS {pg_ret}\n"
        f"LANGUAGE plpgsql\n"
        f"AS $$\nBEGIN\n{pg_body}\nEND;\n$$;"
    )
    return sql, warnings
