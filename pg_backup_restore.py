#!/usr/bin/env python3
"""
Database PG - Ferramenta simples para Backup e Restore de PostgreSQL
Suporta Docker e servidores locais/remotos.
Uso: python pg_backup_restore.py --help
"""

import argparse
import getpass
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path


def run_command(cmd, env=None, check=True, capture_output=False):
    """Executa comando shell de forma segura."""
    print(f"[INFO] Executando: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        env=env or os.environ.copy(),
        check=check,
        capture_output=capture_output,
        text=True
    )
    if capture_output:
        return result.stdout.strip()
    return None


def get_pg_env(password=None):
    """Retorna cópia do ambiente com PGPASSWORD configurado."""
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    return env


def build_docker_cmd(container, pg_cmd, password=None):
    """Constrói comando docker exec para PostgreSQL."""
    docker_cmd = ["docker", "exec"]
    if password:
        docker_cmd.extend(["-e", f"PGPASSWORD={password}"])
    docker_cmd.append(container)
    docker_cmd.extend(pg_cmd)
    return docker_cmd


def prompt_connection_details(prefix):
    """Solicita interativamente os dados de conexão do servidor (host, porta, usuário, senha)."""
    role = "Backup" if prefix == "source" else "Restore"
    print(f"\n=== Servidor de {role} ===")
    host = input("1- host: ").strip() or "localhost"
    port_str = input("2- porta: ").strip() or "5432"
    try:
        port = int(port_str)
    except ValueError:
        port = 5432
    user = input("3- usuario: ").strip() or "postgres"
    password = getpass.getpass("4- senha: ")
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password if password else None
    }


def prompt_backup_path():
    """Solicita interativamente o path onde salvar o arquivo de backup."""
    print("\n=== Arquivo de Backup ===")
    path = input("Path para salvar o backup: ").strip()
    if not path:
        path = "/tmp/backup.dump"
        print(f"[INFO] Usando path padrão: {path}")
    return path


def do_backup(args):
    """Realiza backup usando pg_dump."""
    source = args.source
    backup_file = args.backup_file
    fmt = args.format

    pg_dump_cmd = [
        "pg_dump",
        "-U", source["user"],
        "-h", source.get("host", "localhost"),
        "-p", str(source.get("port", 5432)),
        "-d", source["database"],
        "-F", "c" if fmt == "custom" else "p",
        "-b",  # blobs
        "-v"
    ]

    if source["type"] == "docker":
        cmd = build_docker_cmd(source["container_name"], pg_dump_cmd, source.get("password"))
        # Redirecionar saída para arquivo
        print(f"[INFO] Backup do container {source['container_name']} para {backup_file}")
        with open(backup_file, "wb") as f:
            env = get_pg_env(source.get("password"))
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=f,
                stderr=subprocess.PIPE
            )
            _, stderr = proc.communicate()
            if proc.returncode != 0:
                print(stderr.decode() if stderr else "Erro desconhecido")
                sys.exit(1)
    else:
        # local / remote server
        env = get_pg_env(source.get("password"))
        full_cmd = pg_dump_cmd + ["-f", backup_file]
        run_command(full_cmd, env=env)

    print(f"[SUCCESS] Backup concluído: {backup_file}")


def do_restore(args):
    """Realiza restore usando pg_restore ou psql."""
    target = args.target
    backup_file = args.backup_file
    fmt = args.format

    if fmt == "custom":
        pg_restore_cmd = [
            "pg_restore",
            "-U", target["user"],
            "-h", target.get("host", "localhost"),
            "-p", str(target.get("port", 5432)),
            "-d", target["database"],
            "-v",
            "--clean",
            "--if-exists",
            backup_file
        ]
        if target["type"] == "docker":
            cmd = build_docker_cmd(target["container_name"], pg_restore_cmd, target.get("password"))
            run_command(cmd, env=get_pg_env(target.get("password")))
        else:
            run_command(pg_restore_cmd, env=get_pg_env(target.get("password")))
    else:
        # plain SQL - usa psql
        psql_cmd = [
            "psql",
            "-U", target["user"],
            "-h", target.get("host", "localhost"),
            "-p", str(target.get("port", 5432)),
            "-d", target["database"],
            "-v",
            "-f", backup_file
        ]
        if target["type"] == "docker":
            cmd = build_docker_cmd(target["container_name"], psql_cmd, target.get("password"))
            run_command(cmd, env=get_pg_env(target.get("password")))
        else:
            run_command(psql_cmd, env=get_pg_env(target.get("password")))

    print(f"[SUCCESS] Restore concluído no alvo.")


def do_backup_restore(args):
    """Executa backup + restore direto (usa arquivo temporário)."""
    # Cria arquivo temporário
    suffix = ".dump" if args.format == "custom" else ".sql"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Backup
        backup_args = argparse.Namespace(
            source=args.source,
            backup_file=tmp_path,
            format=args.format
        )
        do_backup(backup_args)

        # Restore
        restore_args = argparse.Namespace(
            target=args.target,
            backup_file=tmp_path,
            format=args.format
        )
        do_restore(restore_args)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
            print(f"[INFO] Arquivo temporário removido.")


def parse_connection_args(prefix, args_dict):
    """Extrai parâmetros de conexão do argparse."""
    conn = {
        "type": getattr(args_dict, f"{prefix}_type"),
        "user": getattr(args_dict, f"{prefix}_user", "postgres"),
        "database": getattr(args_dict, f"{prefix}_db"),
        "host": getattr(args_dict, f"{prefix}_host", "localhost"),
        "port": getattr(args_dict, f"{prefix}_port", 5432),
        "password": getattr(args_dict, f"{prefix}_password", None),
    }
    if conn["type"] == "docker":
        conn["container_name"] = getattr(args_dict, f"{prefix}_container")
    return conn


def main():
    parser = argparse.ArgumentParser(
        description="Ferramenta simples de Backup/Restore PostgreSQL (Docker + Bare-metal)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Comando BACKUP
    p_backup = subparsers.add_parser("backup", help="Realiza apenas o backup")
    p_backup.add_argument("--source-type", choices=["docker", "local"], required=True)
    p_backup.add_argument("--source-container", help="Nome do container (se docker)")
    p_backup.add_argument("--source-host", default="localhost")
    p_backup.add_argument("--source-port", type=int, default=5432)
    p_backup.add_argument("--source-db", required=True)
    p_backup.add_argument("--source-user", default="postgres")
    p_backup.add_argument("--source-password", default=None, help="Senha (ou use $PGPASSWORD)")
    p_backup.add_argument("--backup-file", required=False, help="Path do arquivo de backup (será solicitado se omitido)")
    p_backup.add_argument("--format", choices=["plain", "custom"], default="custom")
    p_backup.set_defaults(func=do_backup)

    # Comando RESTORE
    p_restore = subparsers.add_parser("restore", help="Realiza apenas o restore")
    p_restore.add_argument("--target-type", choices=["docker", "local"], required=True)
    p_restore.add_argument("--target-container", help="Nome do container (se docker)")
    p_restore.add_argument("--target-host", default="localhost")
    p_restore.add_argument("--target-port", type=int, default=5432)
    p_restore.add_argument("--target-db", required=True)
    p_restore.add_argument("--target-user", default="postgres")
    p_restore.add_argument("--target-password", default=None)
    p_restore.add_argument("--backup-file", required=True, help="Path do arquivo de backup para restore")
    p_restore.add_argument("--format", choices=["plain", "custom"], default="custom")
    p_restore.set_defaults(func=do_restore)

    # Comando BACKUP-RESTORE (direto)
    p_br = subparsers.add_parser("backup-restore", help="Backup + Restore direto (sem arquivo intermediário persistente)")
    p_br.add_argument("--source-type", choices=["docker", "local"], required=True)
    p_br.add_argument("--source-container", help="Nome do container fonte")
    p_br.add_argument("--source-host", default="localhost")
    p_br.add_argument("--source-port", type=int, default=5432)
    p_br.add_argument("--source-db", required=True)
    p_br.add_argument("--source-user", default="postgres")
    p_br.add_argument("--source-password", default=None)

    p_br.add_argument("--target-type", choices=["docker", "local"], required=True)
    p_br.add_argument("--target-container", help="Nome do container alvo")
    p_br.add_argument("--target-host", default="localhost")
    p_br.add_argument("--target-port", type=int, default=5432)
    p_br.add_argument("--target-db", required=True)
    p_br.add_argument("--target-user", default="postgres")
    p_br.add_argument("--target-password", default=None)

    p_br.add_argument("--format", choices=["plain", "custom"], default="custom")
    p_br.add_argument("--backup-file", required=False, help="Path do arquivo de backup (será solicitado se omitido)")
    p_br.set_defaults(func=do_backup_restore)

    args = parser.parse_args()

    # Sempre solicita interativamente os dados de conexão (host, porta, usuário, senha)
    # para TODAS as operações de backup/restore, conforme solicitado.
    if args.command in ["backup", "backup-restore"]:
        interactive_source = prompt_connection_details("source")
        # preserva type, db, container se fornecidos via CLI
        base_source = parse_connection_args("source", args)
        base_source.update(interactive_source)
        args.source = base_source
    if args.command in ["restore", "backup-restore"]:
        interactive_target = prompt_connection_details("target")
        base_target = parse_connection_args("target", args)
        base_target.update(interactive_target)
        args.target = base_target

    # Para backup e backup-restore, solicita o path para salvar o backup (se não fornecido)
    if args.command in ["backup", "backup-restore"]:
        if not getattr(args, "backup_file", None):
            args.backup_file = prompt_backup_path()

    # Validações básicas
    if args.command == "backup" and args.source_type == "docker" and not args.source_container:
        parser.error("--source-container é obrigatório quando --source-type=docker")

    if args.command == "restore" and args.target_type == "docker" and not args.target_container:
        parser.error("--target-container é obrigatório quando --target-type=docker")

    if args.command == "backup-restore":
        if args.source_type == "docker" and not args.source_container:
            parser.error("--source-container obrigatório para docker")
        if args.target_type == "docker" and not args.target_container:
            parser.error("--target-container obrigatório para docker")

    # Executa a função
    args.func(args)


if __name__ == "__main__":
    main()
