#!/usr/bin/env python3
"""
Database PG - Instalador simples de PostgreSQL para Debian/Ubuntu
Instala, configura e testa o PostgreSQL de forma automatizada.
Uso: sudo python pg_install.py --help
"""

import argparse
import os
import platform
import secrets
import string
import subprocess
import sys


def detect_os():
    """Detecta se é Debian ou Ubuntu."""
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
        if "ubuntu" in content:
            return "ubuntu"
        elif "debian" in content:
            return "debian"
        else:
            return None
    except FileNotFoundError:
        return None


def generate_password(length=16):
    """Gera senha aleatória segura."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def configure_firewall():
    """Libera a porta 5432 no firewall usando UFW (preferencial) ou iptables."""
    print("[INFO] Configurando firewall para liberar porta 5432 (PostgreSQL)...")
    # Tenta UFW primeiro (padrão no Ubuntu e disponível no Debian)
    try:
        result = subprocess.run(
            ["ufw", "status"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0 and "Status: active" in result.stdout:
            run_cmd(["ufw", "allow", "5432/tcp"])
            print("[SUCCESS] Porta 5432 liberada via UFW.")
            return
    except FileNotFoundError:
        pass

    # Fallback para iptables (comum em Debian minimal)
    try:
        run_cmd([
            "iptables", "-A", "INPUT", "-p", "tcp",
            "--dport", "5432", "-j", "ACCEPT"
        ])
        print("[SUCCESS] Regra adicionada no iptables (lembre-se de persistir se necessário).")
        return
    except Exception:
        pass

    print("[AVISO] Firewall não configurado automaticamente. Libere manualmente a porta 5432/tcp se o firewall estiver ativo.")


def run_cmd(cmd, check=True, capture_output=False, env=None):
    """Executa comando com output amigável."""
    print(f"[INFO] Executando: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=True,
        env=env or os.environ.copy()
    )
    if capture_output:
        return result.stdout.strip()
    return None


def install_postgres(args):
    """Instala PostgreSQL no Debian/Ubuntu."""
    os_type = detect_os()
    if os_type is None:
        print("[ERRO] Sistema operacional não suportado. Apenas Debian e Ubuntu são suportados.")
        sys.exit(1)

    print(f"[INFO] Sistema detectado: {os_type}")

    # Atualiza pacotes
    run_cmd(["apt-get", "update", "-y"])

    # Instala PostgreSQL (usa pacotes do distro para simplicidade)
    run_cmd(["apt-get", "install", "-y", "postgresql", "postgresql-contrib"])

    # Habilita e inicia o serviço
    run_cmd(["systemctl", "enable", "postgresql"])
    run_cmd(["systemctl", "start", "postgresql"])

    print("[SUCCESS] PostgreSQL instalado e serviço iniciado.")

    # Libera porta no firewall (UFW prioritário para Ubuntu/Debian)
    configure_firewall()


def setup_database(args):
    """Cria usuário e banco de dados com senha."""
    user = args.user or "postgres_app"
    db = args.database or "app_db"
    password = args.password or generate_password()

    # Cria usuário (via psql como postgres)
    create_user_sql = f"CREATE USER {user} WITH PASSWORD '{password}';"
    run_cmd([
        "sudo", "-u", "postgres", "psql", "-c", create_user_sql
    ], check=False)  # ignora erro se já existir

    # Cria banco
    create_db_sql = f"CREATE DATABASE {db} OWNER {user};"
    run_cmd([
        "sudo", "-u", "postgres", "psql", "-c", create_db_sql
    ], check=False)

    # Concede privilégios
    grant_sql = f"GRANT ALL PRIVILEGES ON DATABASE {db} TO {user};"
    run_cmd([
        "sudo", "-u", "postgres", "psql", "-c", grant_sql
    ], check=False)

    return user, db, password


def test_postgres(user, db, password):
    """Testa conexão e funcionamento básico."""
    print("[INFO] Testando conexão com PostgreSQL...")
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    try:
        # Testa versão
        version = run_cmd(
            ["psql", "-U", user, "-d", db, "-h", "localhost", "-p", "5432", "-c", "SELECT version();"],
            env=env,
            capture_output=True
        )
        print(f"[INFO] Versão: {version.splitlines()[0] if version else 'N/A'}")

        # Testa query simples
        run_cmd(
            ["psql", "-U", user, "-d", db, "-h", "localhost", "-p", "5432", "-c", "SELECT 1 AS test;"],
            env=env
        )

        print("[SUCCESS] Teste de conexão bem-sucedido! PostgreSQL está funcionando.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERRO] Falha no teste: {e}")
        return False


def print_credentials(user, password, host="localhost", port=5432, db=None):
    """Imprime informações de conexão."""
    print("\n" + "=" * 50)
    print("INFORMAÇÕES DE CONEXÃO POSTGRESQL")
    print("=" * 50)
    print(f"  Usuário: {user}")
    print(f"  Senha:   {password}")
    print(f"  Host:    {host}")
    print(f"  Porta:   {port}")
    if db:
        print(f"  Banco:   {db}")
    print("=" * 50)
    print("IMPORTANTE: Anote a senha! Ela não será mostrada novamente.")
    print("Use: psql -U {} -d {} -h {} -p {}".format(user, db or "postgres", host, port))
    print("=" * 50 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Instalador simples de PostgreSQL para Debian/Ubuntu"
    )
    parser.add_argument("--user", default=None, help="Nome do usuário (padrão: postgres_app)")
    parser.add_argument("--database", default=None, help="Nome do banco (padrão: app_db)")
    parser.add_argument("--password", default=None, help="Senha (será gerada se não informada)")
    parser.add_argument("--skip-install", action="store_true", help="Pula a instalação (assume já instalado)")
    args = parser.parse_args()

    if os.geteuid() != 0 and not args.skip_install:
        print("[ERRO] Execute como root ou com sudo para instalar pacotes.")
        sys.exit(1)

    if not args.skip_install:
        install_postgres(args)

    user, db, password = setup_database(args)
    test_ok = test_postgres(user, db, password)

    print_credentials(user, password, db=db)

    if not test_ok:
        print("[AVISO] O teste falhou, mas a instalação pode estar ok. Verifique manualmente.")
        sys.exit(1)


if __name__ == "__main__":
    main()
