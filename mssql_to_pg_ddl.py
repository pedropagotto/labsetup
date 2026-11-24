#!/usr/bin/env python3
"""
Conversor de Estruturas DDL: Azure SQL / SQL Server -> PostgreSQL.
Permite extrair DDL de um banco SQL Server/Azure SQL ativo ou de arquivos .sql/.bacpac,
convertendo tipos, defaults, constraints e índices para PostgreSQL.
"""

from dataclasses import dataclass, field
import re


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
