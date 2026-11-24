#!/usr/bin/env python3
"""
Conversor de Estruturas DDL: Azure SQL / SQL Server -> PostgreSQL.
Permite extrair DDL de um banco SQL Server/Azure SQL ativo ou de arquivos .sql/.bacpac,
convertendo tipos, defaults, constraints e índices para PostgreSQL.
"""

import argparse
from dataclasses import dataclass, field
import getpass
import re
import sys
import zipfile
from pathlib import Path

import mssql_backup_restore
import pg_backup_restore


@dataclass
class ColumnDef:
    name: str
    data_type: str
    max_length: object = None
    precision: int = None
    scale: int = None
    nullable: bool = True
    default: str = None
    is_identity: bool = False
    identity_seed: int = 1
    identity_increment: int = 1
    is_computed: bool = False
    computed_definition: str = None


@dataclass
class KeyConstraintDef:
    name: str
    constraint_type: str  # "PRIMARY KEY" or "UNIQUE"
    columns: list = field(default_factory=list)


@dataclass
class ForeignKeyDef:
    name: str
    columns: list = field(default_factory=list)
    ref_schema: str = "dbo"
    ref_table: str = ""
    ref_columns: list = field(default_factory=list)
    on_delete: str = None
    on_update: str = None


@dataclass
class CheckConstraintDef:
    name: str
    expression: str


@dataclass
class IndexDef:
    name: str
    columns: list = field(default_factory=list)
    is_unique: bool = False
    where_clause: str = None


@dataclass
class TableDef:
    schema: str
    name: str
    columns: list = field(default_factory=list)
    primary_key: KeyConstraintDef = None
    unique_constraints: list = field(default_factory=list)
    foreign_keys: list = field(default_factory=list)
    check_constraints: list = field(default_factory=list)
    indexes: list = field(default_factory=list)


@dataclass
class DatabaseSchema:
    schemas: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


SIMPLE_TYPE_MAP = {
    "bit": "BOOLEAN",
    "tinyint": "SMALLINT",
    "smallint": "SMALLINT",
    "int": "INTEGER",
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "real": "REAL",
    "float": "DOUBLE PRECISION",
    "money": "NUMERIC(19,4)",
    "smallmoney": "NUMERIC(10,4)",
    "uniqueidentifier": "UUID",
    "date": "DATE",
    "time": "TIME",
    "datetime": "TIMESTAMP",
    "datetime2": "TIMESTAMP",
    "smalldatetime": "TIMESTAMP",
    "datetimeoffset": "TIMESTAMPTZ",
    "text": "TEXT",
    "ntext": "TEXT",
    "image": "BYTEA",
    "xml": "XML",
    "varbinary": "BYTEA",
    "binary": "BYTEA",
}

UNSUPPORTED_TYPE_WARNINGS = {
    "sql_variant": ("TEXT", "Tipo 'sql_variant' convertido para TEXT (revisar compatibilidade)."),
    "geography": ("TEXT", "Tipo espacial 'geography' convertido para TEXT (considere PostGIS geography)."),
    "geometry": ("TEXT", "Tipo espacial 'geometry' convertido para TEXT (considere PostGIS geometry)."),
    "hierarchyid": ("TEXT", "Tipo 'hierarchyid' convertido para TEXT (considere ltree ou TEXT)."),
    "timestamp": ("BYTEA", "Tipo 'timestamp/rowversion' convertido para BYTEA (não tem auto-incremento automático no Postgres)."),
    "rowversion": ("BYTEA", "Tipo 'rowversion' convertido para BYTEA (não tem auto-incremento automático no Postgres)."),
}


def strip_identifier_quotes(name):
    """Remove colchetes [] ou aspas de identificadores T-SQL."""
    return (name or "").strip().strip("[]\"`")


def format_identifier(name, naming="lowercase"):
    """Formata um identificador conforme a estratégia de nomenclatura escolhida."""
    clean = strip_identifier_quotes(name)
    if not clean:
        return clean

    def _to_snake(val):
        s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", val)
        s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
        return s2.lower()

    def _to_preserve(val):
        escaped = val.replace('"', '""')
        return f'"{escaped}"'

    formatters = {
        "lowercase": lambda v: v.lower(),
        "snake_case": _to_snake,
        "preserve": _to_preserve,
    }
    formatter = formatters.get(naming, formatters["lowercase"])
    return formatter(clean)


def map_schema_name(schema, naming="lowercase"):
    """Mapeia 'dbo' para 'public' e formata schemas customizados."""
    clean = strip_identifier_quotes(schema) or "dbo"
    if clean.lower() == "dbo":
        return "public"
    return format_identifier(clean, naming=naming)


def format_qualified_table(schema, table, naming="lowercase"):
    """Retorna schema.tabela formatado para PostgreSQL."""
    pg_schema = map_schema_name(schema, naming=naming)
    pg_table = format_identifier(table, naming=naming)
    return f"{pg_schema}.{pg_table}"


def map_tsql_type(data_type, max_length=None, precision=None, scale=None):
    """Mapeia um tipo T-SQL para o tipo equivalente em PostgreSQL."""
    raw = (data_type or "").strip().lower()
    if raw in SIMPLE_TYPE_MAP:
        return SIMPLE_TYPE_MAP[raw], None

    if raw in UNSUPPORTED_TYPE_WARNINGS:
        return UNSUPPORTED_TYPE_WARNINGS[raw]

    if raw in ("varchar", "nvarchar"):
        if max_length is None or str(max_length).lower() == "max" or int(max_length) <= 0:
            return "TEXT", None
        return f"VARCHAR({int(max_length)})", None

    if raw in ("char", "nchar"):
        if max_length is None or str(max_length).lower() == "max" or int(max_length) <= 0:
            return "TEXT", None
        return f"CHAR({int(max_length)})", None

    if raw in ("decimal", "numeric"):
        if precision is not None and scale is not None:
            return f"NUMERIC({int(precision)},{int(scale)})", None
        if precision is not None:
            return f"NUMERIC({int(precision)})", None
        return "NUMERIC", None

    return "TEXT", f"Tipo desconhecido '{data_type}' convertido para TEXT (revisar)."


def _strip_outer_parens(expr):
    """Remove parênteses externos redundantes do SQL Server, ex: ((1)) -> 1."""
    val = (expr or "").strip()
    while len(val) >= 2 and val.startswith("(") and val.endswith(")"):
        depth = 0
        balanced = True
        for idx, ch in enumerate(val):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and idx < len(val) - 1:
                    balanced = False
                    break
        if balanced and depth == 0:
            val = val[1:-1].strip()
        else:
            break
    return val


def map_default_expr(default_expr, pg_type):
    """Converte expressões DEFAULT do T-SQL para PostgreSQL."""
    if not default_expr:
        return None, None

    cleaned = _strip_outer_parens(default_expr)
    lower = cleaned.lower()

    exact_defaults = {
        "newid()": "gen_random_uuid()",
        "newsequentialid()": "gen_random_uuid()",
        "getdate()": "CURRENT_TIMESTAMP",
        "sysdatetime()": "CURRENT_TIMESTAMP",
        "current_timestamp": "CURRENT_TIMESTAMP",
        "getutcdate()": "(NOW() AT TIME ZONE 'UTC')",
        "sysutcdatetime()": "(NOW() AT TIME ZONE 'UTC')",
        "sysdatetimeoffset()": "CURRENT_TIMESTAMP",
    }
    if lower in exact_defaults:
        return exact_defaults[lower], None

    if pg_type == "BOOLEAN":
        bool_map = {"1": "true", "0": "false", "'1'": "true", "'0'": "false"}
        if lower in bool_map:
            return bool_map[lower], None

    # Remove prefixo N'...' de literais Unicode T-SQL
    if cleaned.startswith("N'") and cleaned.endswith("'"):
        cleaned = cleaned[1:]

    return cleaned, None


def _convert_check_expression(expr, naming="lowercase"):
    """Converte expressões simples de CHECK constraint de T-SQL para PostgreSQL."""
    out = _strip_outer_parens(expr)
    out = re.sub(r"\[([^\]]+)\]", lambda m: format_identifier(m.group(1), naming=naming), out)
    out = re.sub(r"\bN'", "'", out)
    return out


def generate_pg_ddl(db_schema, naming="lowercase"):
    """
    Gera o script DDL completo para PostgreSQL a partir de um DatabaseSchema.
    Retorna (sql_text, warnings_list).
    """
    lines = [
        "-- ============================================================",
        "-- DDL convertida de SQL Server / Azure SQL para PostgreSQL",
        "-- ============================================================",
        "",
    ]
    warnings = list(db_schema.warnings)

    # 1. Schemas (exceto dbo -> public)
    custom_schemas = []
    for sch in db_schema.schemas:
        pg_sch = map_schema_name(sch, naming=naming)
        if pg_sch != "public" and pg_sch not in custom_schemas:
            custom_schemas.append(pg_sch)

    for tbl in db_schema.tables:
        pg_sch = map_schema_name(tbl.schema, naming=naming)
        if pg_sch != "public" and pg_sch not in custom_schemas:
            custom_schemas.append(pg_sch)

    if custom_schemas:
        lines.append("-- 1. Schemas")
        for sch in sorted(custom_schemas):
            lines.append(f"CREATE SCHEMA IF NOT EXISTS {sch};")
        lines.append("")

    # 2. Tabelas (colunas, PK, UNIQUE, CHECK)
    lines.append("-- 2. Tabelas e Constraints locais")
    fk_statements = []
    index_statements = []

    for tbl in db_schema.tables:
        q_table = format_qualified_table(tbl.schema, tbl.name, naming=naming)
        table_items = []

        for col in tbl.columns:
            col_name = format_identifier(col.name, naming=naming)
            if col.is_computed:
                warnings.append(
                    f"Coluna computada {q_table}.{col_name} ({col.computed_definition or ''}) convertida para tipo base; revise GENERATED ALWAYS AS."
                )

            pg_type, type_warn = map_tsql_type(
                col.data_type,
                max_length=col.max_length,
                precision=col.precision,
                scale=col.scale,
            )
            if type_warn:
                warnings.append(f"{q_table}.{col_name}: {type_warn}")

            parts = [f"    {col_name} {pg_type}"]

            if col.is_identity:
                parts.append("GENERATED BY DEFAULT AS IDENTITY")
            elif col.default:
                pg_default, def_warn = map_default_expr(col.default, pg_type)
                if def_warn:
                    warnings.append(f"{q_table}.{col_name} DEFAULT: {def_warn}")
                if pg_default:
                    parts.append(f"DEFAULT {pg_default}")

            if not col.nullable or col.is_identity:
                parts.append("NOT NULL")

            table_items.append(" ".join(parts))

        if tbl.primary_key and tbl.primary_key.columns:
            pk_name = format_identifier(tbl.primary_key.name, naming=naming)
            pk_cols = ", ".join(format_identifier(c, naming=naming) for c in tbl.primary_key.columns)
            table_items.append(f"    CONSTRAINT {pk_name} PRIMARY KEY ({pk_cols})")

        for uq in tbl.unique_constraints:
            uq_name = format_identifier(uq.name, naming=naming)
            uq_cols = ", ".join(format_identifier(c, naming=naming) for c in uq.columns)
            table_items.append(f"    CONSTRAINT {uq_name} UNIQUE ({uq_cols})")

        for chk in tbl.check_constraints:
            chk_name = format_identifier(chk.name, naming=naming)
            chk_expr = _convert_check_expression(chk.expression, naming=naming)
            table_items.append(f"    CONSTRAINT {chk_name} CHECK ({chk_expr})")

        lines.append(f"CREATE TABLE IF NOT EXISTS {q_table} (")
        lines.append(",\n".join(table_items))
        lines.append(");")
        lines.append("")

        for fk in tbl.foreign_keys:
            fk_name = format_identifier(fk.name, naming=naming)
            src_cols = ", ".join(format_identifier(c, naming=naming) for c in fk.columns)
            ref_table = format_qualified_table(fk.ref_schema, fk.ref_table, naming=naming)
            ref_cols = ", ".join(format_identifier(c, naming=naming) for c in fk.ref_columns)
            stmt = (
                f"ALTER TABLE {q_table} ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY ({src_cols}) REFERENCES {ref_table} ({ref_cols})"
            )
            if fk.on_delete and fk.on_delete.upper() != "NO ACTION":
                stmt += f" ON DELETE {fk.on_delete.upper().replace('_', ' ')}"
            if fk.on_update and fk.on_update.upper() != "NO ACTION":
                stmt += f" ON UPDATE {fk.on_update.upper().replace('_', ' ')}"
            fk_statements.append(stmt + ";")

        for idx in tbl.indexes:
            idx_name = format_identifier(idx.name, naming=naming)
            idx_cols = ", ".join(format_identifier(c, naming=naming) for c in idx.columns)
            unique_kw = "UNIQUE " if idx.is_unique else ""
            stmt = f"CREATE {unique_kw}INDEX IF NOT EXISTS {idx_name} ON {q_table} ({idx_cols})"
            if idx.where_clause:
                stmt += f" WHERE {_convert_check_expression(idx.where_clause, naming=naming)}"
            index_statements.append(stmt + ";")

    if fk_statements:
        lines.append("-- 3. Foreign Keys")
        lines.extend(fk_statements)
        lines.append("")

    if index_statements:
        lines.append("-- 4. Índices")
        lines.extend(index_statements)
        lines.append("")

    if warnings:
        lines.append("-- ============================================================")
        lines.append("-- AVISOS E ITENS PARA REVISÃO MANUAL (TODO)")
        lines.append("-- ============================================================")
        for w in warnings:
            lines.append(f"-- TODO: {w}")
        lines.append("")

    return "\n".join(lines), warnings


def _query_live_rows(conn_info, tsql):
    """Executa uma consulta T-SQL via sqlcmd retornando linhas separadas por TAB."""
    full_sql = f"SET NOCOUNT ON; {tsql}"
    args = [
        "-S", mssql_backup_restore.build_sqlcmd_server(conn_info.get("host", "localhost"), conn_info.get("port", 1433)),
        "-U", conn_info["user"],
        "-d", conn_info["database"],
        *mssql_backup_restore.get_sqlcmd_ssl_flags(conn_info.get("ssl_mode", "trust")),
        "-h", "-1",
        "-W",
        "-w", "65535",
        "-s", "\t",
        "-b",
        "-Q", full_sql,
    ]
    out = mssql_backup_restore.run_sqlcmd(args, password=conn_info.get("password"), capture_output=True) or ""
    rows = []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("(") and stripped.endswith("affected)"):
            continue
        rows.append([cell.strip() for cell in line.split("\t")])
    return rows


def extract_schema_from_live_db(conn_info):
    """Extrai tabelas, colunas, constraints, índices e avisos de um SQL Server / Azure SQL ativo."""
    tables_map = {}
    schemas_set = set()
    warnings = []

    # 1. Colunas e tabelas
    col_sql = """
    SELECT
        s.name AS schema_name,
        t.name AS table_name,
        c.name AS column_name,
        ty.name AS type_name,
        c.max_length,
        c.precision,
        c.scale,
        c.is_nullable,
        ISNULL(dc.definition, '') AS default_def,
        c.is_identity,
        ISNULL(CAST(ic.seed_value AS VARCHAR(20)), '1') AS seed_val,
        ISNULL(CAST(ic.increment_value AS VARCHAR(20)), '1') AS inc_val,
        c.is_computed,
        ISNULL(cc.definition, '') AS computed_def
    FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    JOIN sys.columns c ON t.object_id = c.object_id
    JOIN sys.types ty ON c.user_type_id = ty.user_type_id
    LEFT JOIN sys.default_constraints dc ON c.default_object_id = dc.object_id
    LEFT JOIN sys.identity_columns ic ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    LEFT JOIN sys.computed_columns cc ON c.object_id = cc.object_id AND c.column_id = cc.column_id
    WHERE t.is_ms_shipped = 0
    ORDER BY s.name, t.name, c.column_id;
    """
    for row in _query_live_rows(conn_info, col_sql):
        if len(row) < 14:
            continue
        sch, tbl, col_name, dtype, max_len, prec, scale, is_null, d_def, is_id, seed, inc, is_comp, comp_def = row[:14]
        schemas_set.add(sch)
        key = (sch, tbl)
        if key not in tables_map:
            tables_map[key] = TableDef(schema=sch, name=tbl)

        raw_len = int(max_len) if max_len not in ("", "NULL") else None
        if raw_len is not None and raw_len > 0 and dtype.lower() in ("nvarchar", "nchar"):
            raw_len = raw_len // 2

        tables_map[key].columns.append(
            ColumnDef(
                name=col_name,
                data_type=dtype,
                max_length=raw_len,
                precision=int(prec) if prec not in ("", "NULL") else None,
                scale=int(scale) if scale not in ("", "NULL") else None,
                nullable=(is_null == "1"),
                default=d_def or None,
                is_identity=(is_id == "1"),
                identity_seed=int(seed) if seed.isdigit() else 1,
                identity_increment=int(inc) if inc.isdigit() else 1,
                is_computed=(is_comp == "1"),
                computed_definition=comp_def or None,
            )
        )

    # 2. Primary Keys e Unique Constraints
    kc_sql = """
    SELECT
        s.name, t.name, kc.name, kc.type_desc, c.name
    FROM sys.key_constraints kc
    JOIN sys.tables t ON kc.parent_object_id = t.object_id
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    JOIN sys.index_columns ic ON kc.parent_object_id = ic.object_id AND kc.unique_index_id = ic.index_id
    JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
    WHERE t.is_ms_shipped = 0 AND ic.is_included_column = 0
    ORDER BY s.name, t.name, kc.name, ic.key_ordinal;
    """
    kc_acc = {}
    for row in _query_live_rows(conn_info, kc_sql):
        if len(row) < 5:
            continue
        sch, tbl, kc_name, kc_type, col_name = row[:5]
        kc_key = (sch, tbl, kc_name, kc_type)
        kc_acc.setdefault(kc_key, []).append(col_name)

    for (sch, tbl, kc_name, kc_type), cols in kc_acc.items():
        t_obj = tables_map.get((sch, tbl))
        if not t_obj:
            continue
        if "PRIMARY_KEY" in kc_type:
            t_obj.primary_key = KeyConstraintDef(name=kc_name, constraint_type="PRIMARY KEY", columns=cols)
        else:
            t_obj.unique_constraints.append(KeyConstraintDef(name=kc_name, constraint_type="UNIQUE", columns=cols))

    # 3. Foreign Keys
    fk_sql = """
    SELECT
        s.name, t.name, fk.name,
        c_src.name,
        s_ref.name, t_ref.name, c_ref.name,
        fk.delete_referential_action_desc,
        fk.update_referential_action_desc
    FROM sys.foreign_keys fk
    JOIN sys.tables t ON fk.parent_object_id = t.object_id
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
    JOIN sys.columns c_src ON fkc.parent_object_id = c_src.object_id AND fkc.parent_column_id = c_src.column_id
    JOIN sys.tables t_ref ON fk.referenced_object_id = t_ref.object_id
    JOIN sys.schemas s_ref ON t_ref.schema_id = s_ref.schema_id
    JOIN sys.columns c_ref ON fkc.referenced_object_id = c_ref.object_id AND fkc.referenced_column_id = c_ref.column_id
    WHERE t.is_ms_shipped = 0
    ORDER BY s.name, t.name, fk.name, fkc.constraint_column_id;
    """
    fk_acc = {}
    for row in _query_live_rows(conn_info, fk_sql):
        if len(row) < 9:
            continue
        sch, tbl, fk_name, src_col, ref_sch, ref_tbl, ref_col, on_del, on_upd = row[:9]
        fk_key = (sch, tbl, fk_name, ref_sch, ref_tbl, on_del, on_upd)
        entry = fk_acc.setdefault(fk_key, {"src": [], "ref": []})
        entry["src"].append(src_col)
        entry["ref"].append(ref_col)

    for (sch, tbl, fk_name, ref_sch, ref_tbl, on_del, on_upd), cols in fk_acc.items():
        t_obj = tables_map.get((sch, tbl))
        if t_obj:
            t_obj.foreign_keys.append(
                ForeignKeyDef(
                    name=fk_name,
                    columns=cols["src"],
                    ref_schema=ref_sch,
                    ref_table=ref_tbl,
                    ref_columns=cols["ref"],
                    on_delete=on_del,
                    on_update=on_upd,
                )
            )

    # 4. Check Constraints
    chk_sql = """
    SELECT s.name, t.name, cc.name, cc.definition
    FROM sys.check_constraints cc
    JOIN sys.tables t ON cc.parent_object_id = t.object_id
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE t.is_ms_shipped = 0;
    """
    for row in _query_live_rows(conn_info, chk_sql):
        if len(row) < 4:
            continue
        sch, tbl, chk_name, chk_def = row[:4]
        t_obj = tables_map.get((sch, tbl))
        if t_obj:
            t_obj.check_constraints.append(CheckConstraintDef(name=chk_name, expression=chk_def))

    # 5. Índices (excluindo PK e UNIQUE constraints já tratadas)
    idx_sql = """
    SELECT s.name, t.name, i.name, i.is_unique, ISNULL(i.filter_definition, ''), c.name
    FROM sys.indexes i
    JOIN sys.tables t ON i.object_id = t.object_id
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
    JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
    WHERE t.is_ms_shipped = 0
      AND i.is_primary_key = 0
      AND i.is_unique_constraint = 0
      AND i.type > 0
      AND ic.is_included_column = 0
    ORDER BY s.name, t.name, i.name, ic.key_ordinal;
    """
    idx_acc = {}
    for row in _query_live_rows(conn_info, idx_sql):
        if len(row) < 6:
            continue
        sch, tbl, idx_name, is_uq, where_def, col_name = row[:6]
        idx_key = (sch, tbl, idx_name, is_uq == "1", where_def or None)
        idx_acc.setdefault(idx_key, []).append(col_name)

    for (sch, tbl, idx_name, is_uq, where_def), cols in idx_acc.items():
        t_obj = tables_map.get((sch, tbl))
        if t_obj:
            t_obj.indexes.append(IndexDef(name=idx_name, columns=cols, is_unique=is_uq, where_clause=where_def))

    # 6. Views, Procedures e Triggers -> avisos TODO
    extra_sql = """
    SELECT 'VIEW', s.name + '.' + v.name FROM sys.views v JOIN sys.schemas s ON v.schema_id = s.schema_id WHERE v.is_ms_shipped = 0
    UNION ALL
    SELECT 'PROCEDURE', s.name + '.' + p.name FROM sys.procedures p JOIN sys.schemas s ON p.schema_id = s.schema_id WHERE p.is_ms_shipped = 0
    UNION ALL
    SELECT 'TRIGGER', s.name + '.' + tr.name FROM sys.triggers tr JOIN sys.tables t ON tr.parent_id = t.object_id JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE tr.is_ms_shipped = 0;
    """
    for row in _query_live_rows(conn_info, extra_sql):
        if len(row) >= 2:
            warnings.append(f"{row[0]} '{row[1]}' detectada na origem (migração manual necessária).")

    return DatabaseSchema(
        schemas=sorted(schemas_set),
        tables=list(tables_map.values()),
        warnings=warnings,
    )


def _split_top_level_commas(text):
    """Divide uma lista de definições por vírgula respeitando parênteses e aspas."""
    items = []
    current = []
    depth = 0
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_quote:
            in_quote = True
            current.append(ch)
        elif ch == "'" and in_quote:
            if i + 1 < len(text) and text[i + 1] == "'":
                current.append("''")
                i += 1
            else:
                in_quote = False
                current.append(ch)
        elif not in_quote:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth = max(0, depth - 1)
                current.append(ch)
            elif ch == "," and depth == 0:
                item = "".join(current).strip()
                if item:
                    items.append(item)
                current = []
                i += 1
                continue
            else:
                current.append(ch)
        else:
            current.append(ch)
        i += 1
    last = "".join(current).strip()
    if last:
        items.append(last)
    return items


def _parse_qualified_name(raw_name):
    """Separa [schema].[objeto] ou objeto em (schema, objeto)."""
    parts = [strip_identifier_quotes(p) for p in re.split(r"\.(?![^\[]*\])", raw_name.strip())]
    if len(parts) >= 2:
        return parts[-2] or "dbo", parts[-1]
    return "dbo", parts[0]


def _parse_col_list(raw_cols):
    """Extrai lista de nomes de colunas de '( [col1] ASC, [col2] DESC )'."""
    cols = []
    for part in _split_top_level_commas(raw_cols):
        token = part.strip().split()[0]
        cols.append(strip_identifier_quotes(token))
    return cols


def extract_schema_from_sql(sql_text):
    """Faz parsing de um script T-SQL DDL para DatabaseSchema."""
    # Remove comentários /* ... */ e -- ...
    cleaned = re.sub(r"/\*.*?\*/", " ", sql_text, flags=re.DOTALL)
    cleaned = re.sub(r"--[^\r\n]*", " ", cleaned)
    # Normaliza separadores GO em ;
    cleaned = re.sub(r"(?im)^\s*GO\s*$", ";", cleaned)

    schemas = []
    tables_map = {}
    warnings = []

    # Detecta Views / Procedures / Triggers para avisos TODO
    for kind, pattern in (
        ("VIEW", r"(?is)\bCREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+([^\s(]+)"),
        ("PROCEDURE", r"(?is)\bCREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+([^\s(]+)"),
        ("TRIGGER", r"(?is)\bCREATE\s+(?:OR\s+ALTER\s+)?TRIGGER\s+([^\s(]+)"),
    ):
        for m in re.finditer(pattern, cleaned):
            sch, obj = _parse_qualified_name(m.group(1))
            warnings.append(f"{kind} '{sch}.{obj}' detectada no script (migração manual necessária).")

    for m in re.finditer(r"(?is)\bCREATE\s+SCHEMA\s+([^\s;]+)", cleaned):
        schemas.append(strip_identifier_quotes(m.group(1)))

    # CREATE TABLE [schema].[table] ( ... )
    table_pattern = re.compile(r"(?is)\bCREATE\s+TABLE\s+([^\s(]+)\s*\(")
    pos = 0
    while True:
        m = table_pattern.search(cleaned, pos)
        if not m:
            break
        sch, tbl = _parse_qualified_name(m.group(1))
        if sch not in schemas:
            schemas.append(sch)

        start = m.end()
        depth = 1
        idx = start
        in_quote = False
        while idx < len(cleaned) and depth > 0:
            ch = cleaned[idx]
            if ch == "'":
                in_quote = not in_quote
            elif not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            idx += 1
        body = cleaned[start:idx - 1]
        pos = idx

        t_obj = TableDef(schema=sch, name=tbl)
        for item in _split_top_level_commas(body):
            upper_item = item.strip().upper()
            if upper_item.startswith(("CONSTRAINT ", "PRIMARY KEY", "UNIQUE", "FOREIGN KEY", "CHECK")):
                c_name_m = re.match(r"(?is)^CONSTRAINT\s+([^\s]+)\s+(.*)$", item.strip())
                c_name = strip_identifier_quotes(c_name_m.group(1)) if c_name_m else f"{tbl}_constraint"
                rest = c_name_m.group(2).strip() if c_name_m else item.strip()

                pk_m = re.match(r"(?is)^PRIMARY\s+KEY(?:\s+(?:CLUSTERED|NONCLUSTERED))?\s*\(([^)]+)\)", rest)
                uq_m = re.match(r"(?is)^UNIQUE(?:\s+(?:CLUSTERED|NONCLUSTERED))?\s*\(([^)]+)\)", rest)
                fk_m = re.match(
                    r"(?is)^FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+([^\s(]+)\s*\(([^)]+)\)(.*)$",
                    rest,
                )
                chk_m = re.match(r"(?is)^CHECK\s*\((.+)\)$", rest)

                if pk_m:
                    t_obj.primary_key = KeyConstraintDef(name=c_name, constraint_type="PRIMARY KEY", columns=_parse_col_list(pk_m.group(1)))
                elif uq_m:
                    t_obj.unique_constraints.append(KeyConstraintDef(name=c_name, constraint_type="UNIQUE", columns=_parse_col_list(uq_m.group(1))))
                elif fk_m:
                    ref_sch, ref_tbl = _parse_qualified_name(fk_m.group(2))
                    tail = fk_m.group(4) or ""
                    on_del = re.search(r"(?is)ON\s+DELETE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|NO\s+ACTION)", tail)
                    on_upd = re.search(r"(?is)ON\s+UPDATE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|NO\s+ACTION)", tail)
                    t_obj.foreign_keys.append(
                        ForeignKeyDef(
                            name=c_name,
                            columns=_parse_col_list(fk_m.group(1)),
                            ref_schema=ref_sch,
                            ref_table=ref_tbl,
                            ref_columns=_parse_col_list(fk_m.group(3)),
                            on_delete=on_del.group(1).upper() if on_del else None,
                            on_update=on_upd.group(1).upper() if on_upd else None,
                        )
                    )
                elif chk_m:
                    t_obj.check_constraints.append(CheckConstraintDef(name=c_name, expression=chk_m.group(1)))
                continue

            # Definição de coluna
            col_m = re.match(
                r"(?is)^(\[[^\]]+\]|\"[^\"]+\"|\S+)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\(([^)]+)\))?(.*)$",
                item.strip(),
            )
            if not col_m:
                continue
            col_name = strip_identifier_quotes(col_m.group(1))
            dtype = col_m.group(2)
            type_params = col_m.group(3)
            tail = col_m.group(4) or ""

            max_len, prec, scale = None, None, None
            if type_params:
                p_parts = [p.strip() for p in type_params.split(",")]
                if dtype.lower() in ("decimal", "numeric"):
                    prec = int(p_parts[0]) if p_parts[0].isdigit() else None
                    scale = int(p_parts[1]) if len(p_parts) > 1 and p_parts[1].isdigit() else 0
                else:
                    max_len = -1 if p_parts[0].lower() == "max" else (int(p_parts[0]) if p_parts[0].isdigit() else None)

            is_identity = bool(re.search(r"(?is)\bIDENTITY\b", tail))
            nullable = not bool(re.search(r"(?is)\bNOT\s+NULL\b", tail))
            def_m = re.search(r"(?is)\bDEFAULT\s+(\((?:[^()]|\([^()]*\))*\)|'[^']*'|[a-zA-Z0-9_().]+)", tail)
            default_val = def_m.group(1).strip() if def_m else None

            if re.search(r"(?is)\bPRIMARY\s+KEY\b", tail):
                t_obj.primary_key = KeyConstraintDef(name=f"pk_{tbl}", constraint_type="PRIMARY KEY", columns=[col_name])

            t_obj.columns.append(
                ColumnDef(
                    name=col_name,
                    data_type=dtype,
                    max_length=max_len,
                    precision=prec,
                    scale=scale,
                    nullable=nullable,
                    default=default_val,
                    is_identity=is_identity,
                )
            )

        tables_map[(sch, tbl)] = t_obj

    # ALTER TABLE ... ADD CONSTRAINT ...
    alter_fk = re.compile(
        r"(?is)\bALTER\s+TABLE\s+([^\s]+)\s+(?:WITH\s+(?:NO)?CHECK\s+)?ADD\s+CONSTRAINT\s+([^\s]+)\s+"
        r"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+([^\s(]+)\s*\(([^)]+)\)([^;]*)"
    )
    for m in alter_fk.finditer(cleaned):
        sch, tbl = _parse_qualified_name(m.group(1))
        t_obj = tables_map.get((sch, tbl))
        if not t_obj:
            continue
        ref_sch, ref_tbl = _parse_qualified_name(m.group(4))
        tail = m.group(6) or ""
        on_del = re.search(r"(?is)ON\s+DELETE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|NO\s+ACTION)", tail)
        on_upd = re.search(r"(?is)ON\s+UPDATE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|NO\s+ACTION)", tail)
        t_obj.foreign_keys.append(
            ForeignKeyDef(
                name=strip_identifier_quotes(m.group(2)),
                columns=_parse_col_list(m.group(3)),
                ref_schema=ref_sch,
                ref_table=ref_tbl,
                ref_columns=_parse_col_list(m.group(5)),
                on_delete=on_del.group(1).upper() if on_del else None,
                on_update=on_upd.group(1).upper() if on_upd else None,
            )
        )

    # CREATE [UNIQUE] INDEX ...
    idx_pat = re.compile(
        r"(?is)\bCREATE\s+(UNIQUE\s+)?(?:(?:CLUSTERED|NONCLUSTERED)\s+)?INDEX\s+([^\s]+)\s+ON\s+([^\s(]+)\s*\(([^)]+)\)(?:\s+WHERE\s+([^;]+))?"
    )
    for m in idx_pat.finditer(cleaned):
        sch, tbl = _parse_qualified_name(m.group(3))
        t_obj = tables_map.get((sch, tbl))
        if t_obj:
            t_obj.indexes.append(
                IndexDef(
                    name=strip_identifier_quotes(m.group(2)),
                    columns=_parse_col_list(m.group(4)),
                    is_unique=bool(m.group(1)),
                    where_clause=m.group(5).strip() if m.group(5) else None,
                )
            )

    return DatabaseSchema(schemas=schemas, tables=list(tables_map.values()), warnings=warnings)


def extract_schema_from_file(file_path):
    """Carrega e extrai o DatabaseSchema de um arquivo .sql ou .bacpac."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

    if path.suffix.lower() == ".bacpac":
        with zipfile.ZipFile(path, "r") as zf:
            sql_candidates = [n for n in zf.namelist() if n.lower().endswith("model.sql")]
            if not sql_candidates:
                raise ValueError("O arquivo .bacpac não contém 'model.sql'. Exporte um script .sql ou conecte diretamente no banco.")
            sql_text = zf.read(sql_candidates[0]).decode("utf-8", errors="ignore")
        return extract_schema_from_sql(sql_text)

    sql_text = path.read_text(encoding="utf-8", errors="ignore")
    return extract_schema_from_sql(sql_text)


def apply_ddl_to_postgres(ddl_file, pg_conn):
    """Aplica o script DDL convertido em um banco PostgreSQL alvo via psql."""
    psql_args = [
        "-U", pg_conn["user"],
        "-h", pg_conn.get("host", "localhost"),
        "-p", str(pg_conn.get("port", 5432)),
        "-d", pg_conn["database"],
        "-v", "ON_ERROR_STOP=1",
    ]
    print(f"\n[INFO] Aplicando DDL '{ddl_file}' no PostgreSQL ({pg_conn.get('host')}:{pg_conn.get('port')}/{pg_conn.get('database')})...")
    pg_backup_restore.run_pg_tool(
        "psql",
        psql_args,
        password=pg_conn.get("password"),
        sslmode=pg_conn.get("sslmode"),
        input_file=str(ddl_file),
    )
    print("[SUCCESS] DDL aplicada com sucesso no PostgreSQL!")


def convert_ddl(db_schema, output_path, naming="lowercase"):
    """Gera e salva o script DDL PostgreSQL e exibe resumo da conversão."""
    ddl_sql, warnings = generate_pg_ddl(db_schema, naming=naming)
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(ddl_sql, encoding="utf-8")

    print("\n" + "=" * 60)
    print("[SUCCESS] CONVERSÃO DDL CONCLUÍDA!")
    print("=" * 60)
    print(f"  Tabelas convertidas: {len(db_schema.tables)}")
    print(f"  Nomenclatura:        {naming}")
    print(f"  Avisos (TODO):       {len(warnings)}")
    print(f"  Arquivo gerado:      {out_file.resolve()}")
    print("=" * 60)
    if warnings:
        print("\n[AVISO] Itens para revisão manual (registrados também no final do .sql):")
        for w in warnings[:10]:
            print(f"  - {w}")
        if len(warnings) > 10:
            print(f"  ... e mais {len(warnings) - 10} aviso(s) no arquivo.")
    print()
    return out_file, warnings


def run_interactive():
    """Fluxo interativo de conversão DDL SQL Server / Azure SQL -> PostgreSQL."""
    print("\n" + "=" * 60)
    print("CONVERSÃO DE ESTRUTURA DDL: SQL SERVER / AZURE SQL -> POSTGRESQL")
    print("=" * 60)
    print("Escolha a origem da estrutura DDL:")
    print("  1. Banco SQL Server / Azure SQL ativo (extração via sqlcmd)")
    print("  2. Arquivo local (.sql T-SQL ou .bacpac)")
    print("=" * 60)

    try:
        src_choice = input("Escolha uma opção [1-2] (padrão: 1): ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print("\n[INFO] Operação cancelada.")
        return False

    if src_choice == "2":
        file_path = input("Path do arquivo .sql ou .bacpac: ").strip()
        while not file_path:
            print("[ERRO] O caminho do arquivo é obrigatório.")
            file_path = input("Path do arquivo .sql ou .bacpac: ").strip()
        db_schema = extract_schema_from_file(file_path)
    else:
        conn_info = mssql_backup_restore.prompt_connection_details("source")
        print("\n[INFO] Extraindo metadados DDL do servidor...")
        db_schema = extract_schema_from_live_db(conn_info)

    print("\nEstratégia de nomenclatura no PostgreSQL:")
    print("  1. lowercase  (padrão - sem aspas, ex: useraccounts)")
    print("  2. snake_case (ex: UserAccounts -> user_accounts)")
    print("  3. preserve   (preserva case original entre aspas duplas)")
    naming_choice = input("Escolha uma opção [1-3] (padrão: 1): ").strip() or "1"
    naming_map = {"1": "lowercase", "2": "snake_case", "3": "preserve"}
    naming = naming_map.get(naming_choice, "lowercase")

    output_path = input("\nPath para salvar o script PostgreSQL (padrão: ./schema_pg.sql): ").strip() or "./schema_pg.sql"
    out_file, _ = convert_ddl(db_schema, output_path, naming=naming)

    apply_opt = input("Deseja aplicar a DDL convertida agora em um banco PostgreSQL? (s/N): ").strip().lower()
    if apply_opt in ("s", "sim", "y", "yes"):
        pg_conn = pg_backup_restore.prompt_connection_details("target")
        apply_ddl_to_postgres(out_file, pg_conn)

    return True


def main():
    if len(sys.argv) == 1:
        run_interactive()
        return

    parser = argparse.ArgumentParser(
        description="Conversor de estruturas DDL: SQL Server / Azure SQL -> PostgreSQL"
    )
    parser.add_argument("--source-file", help="Arquivo local .sql ou .bacpac de origem")
    parser.add_argument("--source-host", default="localhost")
    parser.add_argument("--source-port", type=int, default=1433)
    parser.add_argument("--source-db", help="Banco de origem (se extração live)")
    parser.add_argument("--source-user", default="sa")
    parser.add_argument("--source-password", default=None)
    parser.add_argument("--source-ssl", choices=["require", "trust", "disable"], default=None)

    parser.add_argument("--output", default="./schema_pg.sql", help="Arquivo .sql de saída (padrão: ./schema_pg.sql)")
    parser.add_argument("--naming", choices=["lowercase", "snake_case", "preserve"], default="lowercase")

    parser.add_argument("--apply", action="store_true", help="Aplica a DDL gerada no PostgreSQL alvo via psql")
    parser.add_argument("--pg-host", default="localhost")
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-db", default=None)
    parser.add_argument("--pg-user", default="postgres")
    parser.add_argument("--pg-password", default=None)
    parser.add_argument("--pg-ssl", choices=["require", "disable", "prefer"], default="prefer")

    args = parser.parse_args()

    if args.source_file:
        db_schema = extract_schema_from_file(args.source_file)
    else:
        if not args.source_db:
            parser.error("Informe --source-file ou --source-db para extração live.")
        pwd = args.source_password or getpass.getpass(f"Senha de origem ({args.source_user}@{args.source_host}): ") or None
        is_az = mssql_backup_restore.is_azure_sql_host(args.source_host)
        conn_info = {
            "type": "local",
            "is_azure": is_az,
            "host": args.source_host,
            "port": args.source_port,
            "database": args.source_db,
            "user": args.source_user,
            "password": pwd,
            "ssl_mode": args.source_ssl or ("require" if is_az else "trust"),
        }
        db_schema = extract_schema_from_live_db(conn_info)

    out_file, _ = convert_ddl(db_schema, args.output, naming=args.naming)

    if args.apply:
        if args.pg_db:
            pg_pwd = args.pg_password or getpass.getpass(f"Senha PostgreSQL ({args.pg_user}@{args.pg_host}): ") or None
            pg_conn = {
                "type": "local",
                "host": args.pg_host,
                "port": args.pg_port,
                "database": args.pg_db,
                "user": args.pg_user,
                "password": pg_pwd,
                "sslmode": args.pg_ssl,
            }
        else:
            pg_conn = pg_backup_restore.prompt_connection_details("target")
        apply_ddl_to_postgres(out_file, pg_conn)


if __name__ == "__main__":
    main()
