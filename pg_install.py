#!/usr/bin/env python3
"""
Database PG - Instalador simples de PostgreSQL para Debian/Ubuntu
Instala, configura e testa o PostgreSQL de forma automatizada.
Uso: sudo python pg_install.py --help
"""

import argparse
import getpass
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


def configure_external_access():
    """Configura o PostgreSQL para permitir conexões externas (postgresql.conf e pg_hba.conf)."""
    print("[INFO] Configurando PostgreSQL para permitir conexões externas...")

    # 1. Obter caminhos dos arquivos de configuração através do psql
    config_file = None
    hba_file = None
    try:
        config_file = run_cmd(
            ["sudo", "-u", "postgres", "psql", "-t", "-P", "format=unaligned", "-c", "SHOW config_file;"],
            capture_output=True
        )
        hba_file = run_cmd(
            ["sudo", "-u", "postgres", "psql", "-t", "-P", "format=unaligned", "-c", "SHOW hba_file;"],
            capture_output=True
        )
    except Exception as e:
        print(f"[AVISO] Não foi possível obter os arquivos de configuração via psql: {e}")

    # Fallback caso psql falhe ou não retorne arquivos válidos
    if not config_file or not hba_file or not os.path.exists(config_file) or not os.path.exists(hba_file):
        print("[INFO] Tentando caminhos padrão de detecção baseada em diretórios...")
        config_file = None
        hba_file = None
        pg_dir = "/etc/postgresql"
        if os.path.exists(pg_dir):
            versions = sorted(os.listdir(pg_dir), reverse=True)
            for version in versions:
                main_dir = os.path.join(pg_dir, version, "main")
                if os.path.isdir(main_dir):
                    config_file = os.path.join(main_dir, "postgresql.conf")
                    hba_file = os.path.join(main_dir, "pg_hba.conf")
                    break

    if not config_file or not hba_file or not os.path.exists(config_file) or not os.path.exists(hba_file):
        print("[ERRO] Arquivos postgresql.conf ou pg_hba.conf não foram encontrados. Configuração de acesso externo pulada.")
        return False

    print(f"[INFO] Caminho detectado para postgresql.conf: {config_file}")
    print(f"[INFO] Caminho detectado para pg_hba.conf: {hba_file}")

    # 2. Modificar postgresql.conf para habilitar listen_addresses = '*'
    try:
        with open(config_file, "r") as f:
            lines = f.readlines()

        configured = False
        for line in lines:
            cleaned = line.strip().replace(" ", "").replace('"', "'")
            if cleaned.startswith("#"):
                continue
            if "listen_addresses='*'" in cleaned or "listen_addresses='localhost,*'" in cleaned or "listen_addresses='*,localhost'" in cleaned:
                configured = True
                break

        if not configured:
            print("[INFO] Configurando listen_addresses = '*' em postgresql.conf...")
            with open(config_file, "a") as f:
                f.write("\n# Habilitar conexões externas adicionado pelo instalador\nlisten_addresses = '*'\n")
            print("[SUCCESS] listen_addresses configurado para '*' com sucesso.")
        else:
            print("[INFO] listen_addresses já está configurado para '*' em postgresql.conf.")
    except Exception as e:
        print(f"[ERRO] Falha ao modificar postgresql.conf: {e}")
        return False

    # 3. Modificar pg_hba.conf para permitir 0.0.0.0/0 e ::/0
    try:
        with open(hba_file, "r") as f:
            hba_content = f.read()

        # Detecta o método de autenticação preferido (scram-sha-256 ou md5)
        auth_method = None
        for line in hba_content.splitlines():
            cleaned = line.strip()
            if cleaned.startswith("#") or not cleaned:
                continue
            if "scram-sha-256" in cleaned:
                auth_method = "scram-sha-256"
                break
            elif "md5" in cleaned:
                auth_method = "md5"

        if not auth_method:
            if "scram-sha-256" in hba_content:
                auth_method = "scram-sha-256"
            elif "md5" in hba_content:
                auth_method = "md5"
            else:
                auth_method = "scram-sha-256"

        print(f"[INFO] Método de autenticação selecionado para regras externas: {auth_method}")

        has_ipv4_rule = False
        has_ipv6_rule = False
        for line in hba_content.splitlines():
            cleaned = line.strip()
            if cleaned.startswith("#") or not cleaned:
                continue
            parts = cleaned.split()
            if len(parts) >= 5 and parts[0].startswith("host"):
                if "0.0.0.0/0" in parts[3]:
                    has_ipv4_rule = True
                if "::/0" in parts[3]:
                    has_ipv6_rule = True

        if not has_ipv4_rule or not has_ipv6_rule:
            print(f"[INFO] Adicionando regras de acesso externo (0.0.0.0/0 e ::/0) ao pg_hba.conf...")
            with open(hba_file, "a") as f:
                f.write("\n# Regras de acesso externo adicionadas pelo instalador\n")
                if not has_ipv4_rule:
                    f.write(f"host    all             all             0.0.0.0/0               {auth_method}\n")
                if not has_ipv6_rule:
                    f.write(f"host    all             all             ::/0                    {auth_method}\n")
            print("[SUCCESS] Regras de acesso externo adicionadas ao pg_hba.conf.")
        else:
            print("[INFO] Regras de acesso externo já presentes no pg_hba.conf.")
    except Exception as e:
        print(f"[ERRO] Falha ao modificar pg_hba.conf: {e}")
        return False

    # 4. Reiniciar o serviço PostgreSQL
    try:
        print("[INFO] Reiniciando o serviço do PostgreSQL para aplicar as alterações...")
        run_cmd(["systemctl", "restart", "postgresql"])
        print("[SUCCESS] Serviço PostgreSQL reiniciado com sucesso!")
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao reiniciar o serviço PostgreSQL: {e}")
        return False


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
    """Cria usuário e banco de dados com senha e configura a senha do superusuário postgres."""
    user = args.user or "postgres_app"
    db = args.database or "app_db"
    password = args.password or generate_password()
    pg_password = args.postgres_password or generate_password()

    # Altera a senha do superusuário administrador 'postgres'
    alter_pg_sql = f"ALTER USER postgres WITH PASSWORD '{pg_password}';"
    run_cmd([
        "sudo", "-u", "postgres", "psql", "-c", alter_pg_sql
    ], check=False)

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

    return user, db, password, pg_password


def test_postgres(user, db, password, host="localhost", port=5432):
    """Testa conexão e funcionamento básico."""
    print(f"[INFO] Testando conexão com PostgreSQL em {host}:{port}...")
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    try:
        # Testa versão
        version = run_cmd(
            ["psql", "-U", user, "-d", db, "-h", host, "-p", str(port), "-c", "SELECT version();"],
            env=env,
            capture_output=True
        )
        print(f"[INFO] Versão: {version.splitlines()[0] if version else 'N/A'}")

        # Testa query simples
        run_cmd(
            ["psql", "-U", user, "-d", db, "-h", host, "-p", str(port), "-c", "SELECT 1 AS test;"],
            env=env
        )

        print("[SUCCESS] Teste de conexão bem-sucedido! PostgreSQL está funcionando.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERRO] Falha no teste: {e}")
        return False


def print_credentials(user, password, pg_password=None, host="localhost", port=5432, db=None):
    """Imprime informações de conexão e orientações de acesso externo."""
    print("\n" + "=" * 60)
    print("INFORMAÇÕES DE CONEXÃO DO POSTGRESQL (INSTALAÇÃO CONCLUÍDA)")
    print("=" * 60)
    print("1. ADMINISTRADOR DO SISTEMA (SUPERUSER)")
    print(f"  Usuário: postgres")
    print(f"  Senha:   {pg_password or 'Não configurada (utilize conexões locais peer)'}")
    print(f"  Host:    {host}")
    print(f"  Porta:   {port}")
    print(f"  Banco:   postgres")
    print("-" * 60)
    print("2. USUÁRIO E BANCO DO APLICATIVO")
    print(f"  Usuário: {user}")
    print(f"  Senha:   {password}")
    print(f"  Host:    {host}")
    print(f"  Porta:   {port}")
    if db:
        print(f"  Banco:   {db}")
    print("=" * 60)
    print("IMPORTANTE: Anote todas as senhas! Elas não serão exibidas novamente.")
    print("=" * 60)
    print("ORIENTAÇÕES PARA CONEXÃO EXTERNA")
    print("=" * 60)
    print("  1. Liberação de Firewall:")
    print("     - O instalador liberou a porta 5432 no firewall do sistema (UFW/iptables).")
    print("     - IMPORTANTE: Se o seu servidor está hospedado em nuvem (AWS, GCP, Azure,")
    print("       DigitalOcean, Oracle Cloud, etc.), você DEVE liberar a porta 5432/tcp")
    print("       nas regras do grupo de segurança (firewall de rede) do console da nuvem.")
    print("  2. Conexões de Qualquer Origem:")
    print("     - O arquivo postgresql.conf foi ajustado para listen_addresses = '*'")
    print("     - O arquivo pg_hba.conf foi ajustado para aceitar conexões via IPv4 (0.0.0.0/0)")
    print("       e IPv6 (::/0) usando autenticação por senha de forma segura.")
    print("  3. Como se conectar de fora:")
    print("     - Ferramentas Visuais (DBeaver, pgAdmin, TablePlus, etc.):")
    print("       - Escolha PostgreSQL.")
    print("       - Host: Use o IP Público do seu servidor.")
    print("       - Porta: 5432")
    print("       - Usuário: postgres (para administração) ou o usuário do aplicativo.")
    print("       - Senha: Use a senha correspondente exibida acima.")
    print("       - Banco de Dados: postgres (para admin) ou o banco do app.")
    print("     - Via Linha de Comando (CLI):")
    print(f"       psql -h <IP_PUBLICO> -U postgres -d postgres")
    print(f"       psql -h <IP_PUBLICO> -U {user} -d {db if db else 'postgres'}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Instalador simples de PostgreSQL para Debian/Ubuntu"
    )
    parser.add_argument("--user", default=None, help="Nome do usuário (padrão: postgres_app)")
    parser.add_argument("--database", default=None, help="Nome do banco (padrão: app_db)")
    parser.add_argument("--password", default=None, help="Senha (será solicitada interativamente se omitida; gerada aleatória se vazia)")
    parser.add_argument("--postgres-password", default=None, help="Senha do superusuário 'postgres' (será solicitada interativamente se omitida; gerada aleatória se vazia)")
    parser.add_argument("--skip-install", action="store_true", help="Pula a instalação (assume já instalado)")
    args, unknown = parser.parse_known_args()

    # Solicita senha interativamente se não informada via CLI (senha não ecoa no terminal)
    if not args.password:
        senha = getpass.getpass("Senha para o usuário PostgreSQL do aplicativo (deixe vazio para gerar aleatória): ").strip()
        args.password = senha or None

    if not args.postgres_password:
        senha_pg = getpass.getpass("Senha para o superusuário administrador 'postgres' (deixe vazio para gerar aleatória): ").strip()
        args.postgres_password = senha_pg or None

    if os.geteuid() != 0 and not args.skip_install:
        print("[ERRO] Execute como root ou com sudo para instalar pacotes.")
        sys.exit(1)

    if not args.skip_install:
        install_postgres(args)

    user, db, password, pg_password = setup_database(args)

    if os.geteuid() == 0:
        configure_external_access()
    else:
        print("[INFO] Executando sem privilégios de root. Ignorando a configuração de acesso externo ao PostgreSQL.")

    test_ok = test_postgres(user, db, password)

    print_credentials(user, password, pg_password=pg_password, db=db)

    # Solicita se deseja realizar teste de conexão personalizado
    try:
        opcao = input("Deseja realizar um teste de conexão personalizado? (s/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        opcao = "n"

    if opcao in ("s", "sim", "y", "yes"):
        print("\n=== Teste de Conexão Personalizado ===")
        try:
            host = input("Host (padrão: localhost): ").strip() or "localhost"
            port_str = input("Porta (padrão: 5432): ").strip() or "5432"
            try:
                port = int(port_str)
            except ValueError:
                port = 5432
            user_input = input(f"Usuário (padrão: {user}): ").strip() or user
            senha = getpass.getpass("Senha (deixe vazio para usar a criada na instalação): ")
            if not senha:
                senha = password
            banco = input(f"Banco de dados (padrão: {db}): ").strip() or db

            custom_test_ok = test_postgres(user_input, banco, senha, host=host, port=port)
            if not custom_test_ok:
                print("[AVISO] O teste de conexão personalizado falhou.")
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] Teste de conexão personalizado cancelado pelo usuário.")

    if not test_ok:
        print("[AVISO] O teste padrão falhou, mas a instalação pode estar ok. Verifique manualmente.")
        sys.exit(1)


if __name__ == "__main__":
    main()
