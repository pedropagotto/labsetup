#!/usr/bin/env python3
"""
Database MSSQL / Azure SQL - Ferramenta para Backup, Restore e Gerenciamento de Usuários.
Suporta Azure SQL Database, SQL Server local/remoto e containers Docker.
Uso: python mssql_backup_restore.py --help
"""

import getpass
import os
import secrets
import shutil
import string
import subprocess
from pathlib import Path


DEFAULT_SQLCMD_IMAGE = os.environ.get("MSSQL_TOOLS_IMAGE", "mcr.microsoft.com/mssql-tools:latest")
DEFAULT_SQLPACKAGE_IMAGE = os.environ.get("MSSQL_SQLPACKAGE_IMAGE", "mcr.microsoft.com/mssql/sqlpackage:latest")


def generate_random_password(length=16):
    """Gera uma senha segura compatível com a política de complexidade do SQL Server/Azure SQL."""
    if length < 12:
        length = 12
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    symbols = "!@#$%^&*"
    all_chars = upper + lower + digits + symbols

    required = [
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]
    rest = [secrets.choice(all_chars) for _ in range(length - len(required))]
    chars = required + rest
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def is_azure_sql_host(host):
    """Detecta se o host pertence ao Azure SQL Database (.database.windows.net)."""
    return ".database.windows.net" in (host or "").strip().lower()


def build_sqlcmd_server(host, port=1433):
    """Formata o endereço servidor,porta para uso no sqlcmd."""
    host = (host or "localhost").strip()
    port = int(port or 1433)
    return f"{host},{port}"


def get_sqlcmd_ssl_flags(ssl_mode):
    """Retorna as flags de criptografia/certificado do sqlcmd conforme o modo SSL."""
    ssl_flag_map = {
        "require": ["-N"],
        "trust": ["-N", "-C"],
        "disable": [],
    }
    return list(ssl_flag_map.get(ssl_mode, ["-N", "-C"]))


def get_sqlcmd_env(password=None):
    """Retorna cópia do ambiente com SQLCMDPASSWORD configurado."""
    env = os.environ.copy()
    if password:
        env["SQLCMDPASSWORD"] = password
    return env


def build_sqlpackage_conn_str(conn):
    """Constrói a connection string ADO.NET para uso com o sqlpackage."""
    host = conn.get("host", "localhost")
    port = int(conn.get("port", 1433))
    database = conn["database"]
    user = conn["user"]
    password = conn.get("password") or ""
    ssl_mode = conn.get("ssl_mode", "trust")

    ssl_props_map = {
        "require": ("True", "False"),
        "trust": ("True", "True"),
        "disable": ("False", "True"),
    }
    encrypt, trust_cert = ssl_props_map.get(ssl_mode, ("True", "True"))

    return (
        f"Server=tcp:{host},{port};"
        f"Initial Catalog={database};"
        f"Persist Security Info=False;"
        f"User ID={user};"
        f"Password={password};"
        f"MultipleActiveResultSets=False;"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_cert};"
        f"Connection Timeout=30;"
    )


def find_local_tool(tool_name, extra_paths=None):
    """Procura o executável no PATH ou em diretórios padrão da Microsoft."""
    found = shutil.which(tool_name)
    if found:
        return found
    for candidate in extra_paths or []:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_local_sqlcmd():
    """Localiza o binário sqlcmd no sistema."""
    return find_local_tool(
        "sqlcmd",
        [
            "/opt/mssql-tools18/bin/sqlcmd",
            "/opt/mssql-tools/bin/sqlcmd",
            "/usr/local/bin/sqlcmd",
        ],
    )


def find_local_sqlpackage():
    """Localiza o binário sqlpackage no sistema."""
    return find_local_tool(
        "sqlpackage",
        [
            "/opt/sqlpackage/sqlpackage",
            "/usr/local/bin/sqlpackage",
            str(Path.home() / ".dotnet/tools/sqlpackage"),
        ],
    )


def build_docker_exec_cmd(container, inner_cmd, password=None):
    """Constrói comando docker exec para executar comandos dentro de um container SQL Server."""
    docker_cmd = ["docker", "exec"]
    if password:
        docker_cmd.extend(["-e", f"SQLCMDPASSWORD={password}"])
    docker_cmd.append(container)
    docker_cmd.extend(inner_cmd)
    return docker_cmd


def run_sqlcmd(cmd_args, password=None, input_file=None, capture_output=False, check=True):
    """
    Executa o comando sqlcmd localmente ou via fallback em container Docker.
    """
    env = get_sqlcmd_env(password)
    local_bin = find_local_sqlcmd()

    if local_bin:
        cmd = [local_bin] + cmd_args
        if input_file:
            print(f"[INFO] Executando local: {' '.join(cmd)} < {input_file}")
            with open(input_file, "rb") as f_in:
                result = subprocess.run(
                    cmd, env=env, stdin=f_in, check=check,
                    capture_output=capture_output, text=capture_output
                )
        else:
            print(f"[INFO] Executando local: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, env=env, check=check,
                capture_output=capture_output, text=capture_output
            )
        return result.stdout.strip() if capture_output and result.stdout else None

    if shutil.which("docker") is not None:
        print("[AVISO] 'sqlcmd' não encontrado localmente. Tentando executar via container Docker temporário...")
        docker_cmd = ["docker", "run", "--rm", "-i", "--network=host"]
        if password:
            docker_cmd.extend(["-e", f"SQLCMDPASSWORD={password}"])
        docker_cmd.extend([DEFAULT_SQLCMD_IMAGE, "/opt/mssql-tools/bin/sqlcmd"])
        docker_cmd.extend(cmd_args)

        if input_file:
            print(f"[INFO] Executando via Docker: {' '.join(docker_cmd)} < {input_file}")
            with open(input_file, "rb") as f_in:
                result = subprocess.run(
                    docker_cmd, stdin=f_in, check=check,
                    capture_output=capture_output, text=capture_output
                )
        else:
            print(f"[INFO] Executando via Docker: {' '.join(docker_cmd)}")
            result = subprocess.run(
                docker_cmd, check=check,
                capture_output=capture_output, text=capture_output
            )
        return result.stdout.strip() if capture_output and result.stdout else None

    raise FileNotFoundError(
        "Não foi possível encontrar 'sqlcmd' localmente nem o comando 'docker' para executar o fallback."
    )


def run_sqlpackage(cmd_args, mount_dir=None, check=True):
    """
    Executa o utilitário sqlpackage localmente ou via fallback em container Docker.
    """
    local_bin = find_local_sqlpackage()
    if local_bin:
        cmd = [local_bin] + cmd_args
        print(f"[INFO] Executando local: {local_bin} ...")
        subprocess.run(cmd, check=check)
        return

    if shutil.which("docker") is not None:
        print("[AVISO] 'sqlpackage' não encontrado localmente. Tentando executar via container Docker temporário...")
        docker_cmd = ["docker", "run", "--rm", "--network=host"]
        if mount_dir:
            abs_dir = str(Path(mount_dir).resolve())
            docker_cmd.extend(["-v", f"{abs_dir}:{abs_dir}"])
        docker_cmd.append(DEFAULT_SQLPACKAGE_IMAGE)
        docker_cmd.extend(cmd_args)
        print(f"[INFO] Executando via Docker ({DEFAULT_SQLPACKAGE_IMAGE})...")
        subprocess.run(docker_cmd, check=check)
        return

    raise FileNotFoundError(
        "Não foi possível encontrar 'sqlpackage' localmente nem o comando 'docker' para executar o fallback."
    )


def prompt_ssl_mode(host):
    """Solicita o modo SSL/criptografia adequado para SQL Server ou Azure SQL."""
    is_azure = is_azure_sql_host(host)
    print("6- Configuração SSL / Criptografia (SQL Server / Azure SQL):")
    print("   [1] Sim - Verificar Certificado (Exigido / Azure SQL)")
    print("   [2] Sim - Confiar no Certificado (SQL Server Local / Docker / VPS)")
    print("   [3] Desativado (Apenas servidor local sem SSL)")

    default_opt = "1" if is_azure else "2"
    ssl_choice = input(f"   Escolha uma opção [1-3] (padrão: {default_opt}): ").strip() or default_opt

    ssl_map = {
        "1": "require",
        "2": "trust",
        "3": "disable",
    }
    return ssl_map.get(ssl_choice, "require" if is_azure else "trust")


def prompt_connection_details(prefix, require_db=True):
    """Solicita interativamente os dados de conexão (SQL Server ou Azure SQL)."""
    role = "Backup (Origem)" if prefix == "source" else "Restore (Destino)"
    print(f"\n=== Servidor SQL Server / Azure SQL de {role} ===")
    host = input("1- Host/IP (ex: localhost ou servidor.database.windows.net): ").strip() or "localhost"

    port_str = input("2- Porta (padrão 1433): ").strip() or "1433"
    try:
        port = int(port_str)
    except ValueError:
        port = 1433

    db = ""
    if require_db:
        db = input("3- Nome do Banco de Dados (Database): ").strip()
        while not db:
            print("[ERRO] Nome do banco de dados é obrigatório.")
            db = input("3- Nome do Banco de Dados (Database): ").strip()
    else:
        db = input("3- Banco de Dados inicial (padrão master): ").strip() or "master"

    default_user = "sqladmin" if is_azure_sql_host(host) else "sa"
    user = input(f"4- Usuário (padrão {default_user}): ").strip() or default_user
    password = getpass.getpass("5- Senha: ")
    ssl_mode = prompt_ssl_mode(host)

    return {
        "type": "local",
        "is_azure": is_azure_sql_host(host),
        "host": host,
        "port": port,
        "database": db,
        "user": user,
        "password": password if password else None,
        "ssl_mode": ssl_mode,
    }
