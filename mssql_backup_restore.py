#!/usr/bin/env python3
"""
Database MSSQL / Azure SQL - Ferramenta para Backup, Restore e Gerenciamento de Usuários.
Suporta Azure SQL Database, SQL Server local/remoto e containers Docker.
Uso: python mssql_backup_restore.py --help
"""

import argparse
import getpass
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
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


def prompt_backup_path(fmt="bacpac"):
    """Solicita interativamente o path onde salvar o arquivo de backup."""
    default_ext = ".bacpac" if fmt == "bacpac" else ".bak"
    default_path = f"/tmp/backup{default_ext}"
    print("\n=== Arquivo de Backup ===")
    path = input(f"Path para salvar o backup (padrão: {default_path}): ").strip()
    if not path:
        path = default_path
        print(f"[INFO] Usando path padrão: {path}")
    return path


def prompt_backup_format(source=None, target=None):
    """Solicita o formato do backup (.bacpac universal ou .bak para SQL Server)."""
    if (source and source.get("is_azure")) or (target and target.get("is_azure")):
        print("[INFO] Azure SQL detectado: utilizando formato universal .bacpac (sqlpackage).")
        return "bacpac"

    print("\n=== Formato do Backup ===")
    print("  1. .bacpac (Universal - funciona em Azure SQL e SQL Server, permite migração cruzada)")
    print("  2. .bak    (Nativo SQL Server - apenas SQL Server local/Docker)")
    choice = input("Escolha o formato [1-2] (padrão: 1): ").strip() or "1"
    return "bak" if choice == "2" else "bacpac"


def _escape_tsql_str(value):
    """Escapa aspas simples para uso seguro em literais T-SQL."""
    return str(value).replace("'", "''")


def _run_docker_sqlcmd(container, server_db, user, password, ssl_mode, query):
    """Executa uma query T-SQL via sqlcmd dentro de um container Docker SQL Server."""
    sqlcmd_args = [
        "/opt/mssql-tools18/bin/sqlcmd",
        "-S", "localhost",
        "-U", user,
        "-d", server_db,
        *get_sqlcmd_ssl_flags(ssl_mode),
        "-b",
        "-Q", query,
    ]
    cmd = build_docker_exec_cmd(container, sqlcmd_args, password=password)
    print(f"[INFO] Executando no container {container}: sqlcmd -d {server_db} ...")
    subprocess.run(cmd, check=True)


def do_backup(args):
    """Realiza backup de SQL Server ou Azure SQL (.bacpac via sqlpackage ou .bak via sqlcmd)."""
    source = args.source
    backup_file = str(Path(args.backup_file).resolve())
    fmt = getattr(args, "format", "bacpac")
    Path(backup_file).parent.mkdir(parents=True, exist_ok=True)

    if fmt == "bacpac":
        conn_str = build_sqlpackage_conn_str(source)
        run_sqlpackage(
            [
                "/Action:Export",
                f"/SourceConnectionString:{conn_str}",
                f"/TargetFile:{backup_file}",
            ],
            mount_dir=Path(backup_file).parent,
        )
        print(f"[SUCCESS] Backup (.bacpac) concluído: {backup_file}")
        return

    # Formato .bak (apenas SQL Server)
    if source.get("is_azure") or is_azure_sql_host(source.get("host")):
        raise ValueError("Azure SQL Database não suporta backup local em formato .bak. Utilize --format bacpac.")

    db = source["database"]
    if source.get("type") == "docker":
        container = source["container_name"]
        container_bak = f"/tmp/{db}_backup.bak"
        tsql = (
            f"BACKUP DATABASE [{db}] TO DISK = N'{_escape_tsql_str(container_bak)}' "
            f"WITH FORMAT, INIT, NAME = N'{_escape_tsql_str(db)}-Full';"
        )
        _run_docker_sqlcmd(
            container,
            "master",
            source["user"],
            source.get("password"),
            source.get("ssl_mode", "trust"),
            tsql,
        )
        print(f"[INFO] Copiando backup do container {container}:{container_bak} para {backup_file}...")
        subprocess.run(["docker", "cp", f"{container}:{container_bak}", backup_file], check=True)
        subprocess.run(["docker", "exec", container, "rm", "-f", container_bak], check=False)
    else:
        tsql = (
            f"BACKUP DATABASE [{db}] TO DISK = N'{_escape_tsql_str(backup_file)}' "
            f"WITH FORMAT, INIT, NAME = N'{_escape_tsql_str(db)}-Full';"
        )
        sqlcmd_args = [
            "-S", build_sqlcmd_server(source.get("host", "localhost"), source.get("port", 1433)),
            "-U", source["user"],
            "-d", "master",
            *get_sqlcmd_ssl_flags(source.get("ssl_mode", "trust")),
            "-b",
            "-Q", tsql,
        ]
        run_sqlcmd(sqlcmd_args, password=source.get("password"))

    print(f"[SUCCESS] Backup (.bak) concluído: {backup_file}")


def do_restore(args):
    """Realiza restore em SQL Server ou Azure SQL (.bacpac via sqlpackage ou .bak via sqlcmd)."""
    target = args.target
    backup_file = str(Path(args.backup_file).resolve())
    fmt = getattr(args, "format", "bacpac")

    if fmt == "bacpac":
        conn_str = build_sqlpackage_conn_str(target)
        run_sqlpackage(
            [
                "/Action:Import",
                f"/TargetConnectionString:{conn_str}",
                f"/SourceFile:{backup_file}",
            ],
            mount_dir=Path(backup_file).parent,
        )
        print(f"[SUCCESS] Restore (.bacpac) concluído no alvo '{target['database']}'.")
        return

    # Formato .bak (apenas SQL Server)
    if target.get("is_azure") or is_azure_sql_host(target.get("host")):
        raise ValueError("Azure SQL Database não suporta restore de arquivo .bak local. Utilize --format bacpac.")

    db = target["database"]
    if target.get("type") == "docker":
        container = target["container_name"]
        container_bak = f"/tmp/{db}_restore.bak"
        print(f"[INFO] Copiando {backup_file} para {container}:{container_bak}...")
        subprocess.run(["docker", "cp", backup_file, f"{container}:{container_bak}"], check=True)
        tsql = (
            f"IF DB_ID(N'{_escape_tsql_str(db)}') IS NOT NULL "
            f"ALTER DATABASE [{db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"RESTORE DATABASE [{db}] FROM DISK = N'{_escape_tsql_str(container_bak)}' WITH REPLACE; "
            f"ALTER DATABASE [{db}] SET MULTI_USER;"
        )
        _run_docker_sqlcmd(
            container,
            "master",
            target["user"],
            target.get("password"),
            target.get("ssl_mode", "trust"),
            tsql,
        )
        subprocess.run(["docker", "exec", container, "rm", "-f", container_bak], check=False)
    else:
        tsql = (
            f"IF DB_ID(N'{_escape_tsql_str(db)}') IS NOT NULL "
            f"ALTER DATABASE [{db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"RESTORE DATABASE [{db}] FROM DISK = N'{_escape_tsql_str(backup_file)}' WITH REPLACE; "
            f"ALTER DATABASE [{db}] SET MULTI_USER;"
        )
        sqlcmd_args = [
            "-S", build_sqlcmd_server(target.get("host", "localhost"), target.get("port", 1433)),
            "-U", target["user"],
            "-d", "master",
            *get_sqlcmd_ssl_flags(target.get("ssl_mode", "trust")),
            "-b",
            "-Q", tsql,
        ]
        run_sqlcmd(sqlcmd_args, password=target.get("password"))

    print(f"[SUCCESS] Restore (.bak) concluído no alvo '{db}'.")


def do_backup_restore(args):
    """Executa backup + restore direto (usa arquivo temporário)."""
    fmt = getattr(args, "format", "bacpac")
    suffix = ".bacpac" if fmt == "bacpac" else ".bak"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        backup_args = argparse.Namespace(
            source=args.source,
            backup_file=tmp_path,
            format=fmt,
        )
        do_backup(backup_args)

        restore_args = argparse.Namespace(
            target=args.target,
            backup_file=tmp_path,
            format=fmt,
        )
        do_restore(restore_args)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
            print("[INFO] Arquivo temporário removido.")


def parse_connection_args(prefix, args_dict):
    """Extrai parâmetros de conexão do argparse."""
    host = getattr(args_dict, f"{prefix}_host", "localhost")
    conn = {
        "type": getattr(args_dict, f"{prefix}_type"),
        "is_azure": is_azure_sql_host(host),
        "user": getattr(args_dict, f"{prefix}_user", "sa"),
        "database": getattr(args_dict, f"{prefix}_db"),
        "host": host,
        "port": getattr(args_dict, f"{prefix}_port", 1433),
        "password": getattr(args_dict, f"{prefix}_password", None),
        "ssl_mode": getattr(args_dict, f"{prefix}_ssl", "require" if is_azure_sql_host(host) else "trust"),
    }
    if conn["type"] == "docker":
        conn["container_name"] = getattr(args_dict, f"{prefix}_container")
    return conn


def _prompt_conn_docker(role):
    """Solicita dados de conexão para um container Docker SQL Server."""
    print(f"\n--- Dados de Conexão do SQL Server (Container Docker de {role}) ---")
    container = input("Nome do container Docker: ").strip()
    while not container:
        print("[ERRO] Nome do container é obrigatório.")
        container = input("Nome do container Docker: ").strip()

    db = input("Nome do banco de dados: ").strip()
    while not db:
        print("[ERRO] Nome do banco de dados é obrigatório.")
        db = input("Nome do banco de dados: ").strip()

    port_str = input("Porta mapeada no host (padrão 1433): ").strip() or "1433"
    try:
        port = int(port_str)
    except ValueError:
        port = 1433

    user = input("Usuário (padrão: sa): ").strip() or "sa"
    password = getpass.getpass("Senha: ")

    return {
        "type": "docker",
        "is_azure": False,
        "container_name": container,
        "host": "localhost",
        "port": port,
        "database": db,
        "user": user,
        "password": password if password else None,
        "ssl_mode": "trust",
    }


def run_interactive():
    """Menu interativo de operações SQL Server / Azure SQL."""
    print("=" * 60)
    print("DATABASE MSSQL / AZURE SQL - MIGRAÇÃO, BACKUP E USUÁRIOS")
    print("=" * 60)
    print("Escolha o método/operação:")
    print("  1. Backup de Servidor Remoto/Azure SQL para Arquivo Local + Restore (2 etapas)")
    print("  2. Backup + Restore Direto entre Servidores (SQL Server / Azure SQL / VPS)")
    print("  3. Migração envolvendo Docker Container SQL Server")
    print("  4. Criar usuário com permissões (Owner, Readonly, Writer)")
    print("  5. Redefinir senha de usuário (SQL Server / Azure SQL)")
    print("=" * 60)
    try:
        escolha = input("Escolha uma opção [1-5]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[INFO] Operação cancelada.")
        sys.exit(0)

    valid_choices = {"1", "2", "3", "4", "5"}
    if escolha not in valid_choices:
        print("[ERRO] Opção inválida.")
        sys.exit(1)

    args = argparse.Namespace()

    def _handle_two_step():
        args.command = "backup"
        args.source = prompt_connection_details("source")
        args.format = prompt_backup_format(source=args.source)
        args.backup_file = prompt_backup_path(args.format)
        print("\n[INFO] Iniciando Etapa 1/2: Gerando arquivo de backup...")
        do_backup(args)

        args.command = "restore"
        args.target = prompt_connection_details("target")
        print("\n[INFO] Iniciando Etapa 2/2: Restaurando no servidor de destino...")
        do_restore(args)
        args.func = lambda x: print("\n[SUCCESS] Migração em duas etapas concluída com sucesso!")

    def _handle_direct():
        args.command = "backup-restore"
        args.source = prompt_connection_details("source")
        args.target = prompt_connection_details("target")
        args.format = prompt_backup_format(source=args.source, target=args.target)
        args.func = do_backup_restore

    def _handle_docker():
        print("\nConfiguração de Docker:")
        s_type = input("Origem é Docker? (s/N): ").strip().lower()
        args.source = _prompt_conn_docker("Origem") if s_type in ("s", "sim", "y", "yes") else prompt_connection_details("source")

        t_type = input("Destino é Docker? (s/N): ").strip().lower()
        args.target = _prompt_conn_docker("Destino") if t_type in ("s", "sim", "y", "yes") else prompt_connection_details("target")

        args.format = prompt_backup_format(source=args.source, target=args.target)
        args.command = "backup-restore"
        args.func = do_backup_restore

    def _handle_create_user():
        args.command = "create-user"
        args.func = lambda x: print("[INFO] Criação de usuário será implementada na próxima etapa.")

    def _handle_reset_password():
        args.command = "reset-user-password"
        args.func = lambda x: print("[INFO] Redefinição de senha será implementada na próxima etapa.")

    handlers = {
        "1": _handle_two_step,
        "2": _handle_direct,
        "3": _handle_docker,
        "4": _handle_create_user,
        "5": _handle_reset_password,
    }
    handlers[escolha]()
    return args


def main():
    if len(sys.argv) == 1:
        args = run_interactive()
        args.func(args)
        return

    parser = argparse.ArgumentParser(
        description="Ferramenta de Backup/Restore e Usuários para SQL Server e Azure SQL"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Comando BACKUP
    p_backup = subparsers.add_parser("backup", help="Realiza apenas o backup")
    p_backup.add_argument("--source-type", choices=["docker", "local"], required=True)
    p_backup.add_argument("--source-container", help="Nome do container (se docker)")
    p_backup.add_argument("--source-host", default="localhost")
    p_backup.add_argument("--source-port", type=int, default=1433)
    p_backup.add_argument("--source-db", required=True)
    p_backup.add_argument("--source-user", default="sa")
    p_backup.add_argument("--source-password", default=None, help="Senha (ou use $SQLCMDPASSWORD)")
    p_backup.add_argument("--source-ssl", choices=["require", "trust", "disable"], default=None)
    p_backup.add_argument("--backup-file", required=False, help="Path do arquivo de backup")
    p_backup.add_argument("--format", choices=["bacpac", "bak"], default="bacpac")
    p_backup.set_defaults(func=do_backup)

    # Comando RESTORE
    p_restore = subparsers.add_parser("restore", help="Realiza apenas o restore")
    p_restore.add_argument("--target-type", choices=["docker", "local"], required=True)
    p_restore.add_argument("--target-container", help="Nome do container (se docker)")
    p_restore.add_argument("--target-host", default="localhost")
    p_restore.add_argument("--target-port", type=int, default=1433)
    p_restore.add_argument("--target-db", required=True)
    p_restore.add_argument("--target-user", default="sa")
    p_restore.add_argument("--target-password", default=None)
    p_restore.add_argument("--target-ssl", choices=["require", "trust", "disable"], default=None)
    p_restore.add_argument("--backup-file", required=True, help="Path do arquivo de backup para restore")
    p_restore.add_argument("--format", choices=["bacpac", "bak"], default="bacpac")
    p_restore.set_defaults(func=do_restore)

    # Comando BACKUP-RESTORE
    p_br = subparsers.add_parser("backup-restore", help="Backup + Restore direto (arquivo temporário)")
    p_br.add_argument("--source-type", choices=["docker", "local"], required=True)
    p_br.add_argument("--source-container", help="Nome do container fonte")
    p_br.add_argument("--source-host", default="localhost")
    p_br.add_argument("--source-port", type=int, default=1433)
    p_br.add_argument("--source-db", required=True)
    p_br.add_argument("--source-user", default="sa")
    p_br.add_argument("--source-password", default=None)
    p_br.add_argument("--source-ssl", choices=["require", "trust", "disable"], default=None)

    p_br.add_argument("--target-type", choices=["docker", "local"], required=True)
    p_br.add_argument("--target-container", help="Nome do container alvo")
    p_br.add_argument("--target-host", default="localhost")
    p_br.add_argument("--target-port", type=int, default=1433)
    p_br.add_argument("--target-db", required=True)
    p_br.add_argument("--target-user", default="sa")
    p_br.add_argument("--target-password", default=None)
    p_br.add_argument("--target-ssl", choices=["require", "trust", "disable"], default=None)

    p_br.add_argument("--format", choices=["bacpac", "bak"], default="bacpac")
    p_br.add_argument("--backup-file", required=False, help="Path do arquivo de backup")
    p_br.set_defaults(func=do_backup_restore)

    args = parser.parse_args()

    if args.command in ("backup", "backup-restore"):
        args.source = parse_connection_args("source", args)
        if not args.source.get("password"):
            args.source["password"] = getpass.getpass(f"Senha de origem ({args.source['user']}@{args.source['host']}): ") or None
    if args.command in ("restore", "backup-restore"):
        args.target = parse_connection_args("target", args)
        if not args.target.get("password"):
            args.target["password"] = getpass.getpass(f"Senha de destino ({args.target['user']}@{args.target['host']}): ") or None

    if args.command in ("backup", "backup-restore") and not getattr(args, "backup_file", None):
        args.backup_file = prompt_backup_path(args.format)

    if args.command == "backup" and args.source_type == "docker" and not args.source_container:
        parser.error("--source-container é obrigatório quando --source-type=docker")
    if args.command == "restore" and args.target_type == "docker" and not args.target_container:
        parser.error("--target-container é obrigatório quando --target-type=docker")
    if args.command == "backup-restore":
        if args.source_type == "docker" and not args.source_container:
            parser.error("--source-container obrigatório para docker")
        if args.target_type == "docker" and not args.target_container:
            parser.error("--target-container obrigatório para docker")

    args.func(args)


if __name__ == "__main__":
    main()
