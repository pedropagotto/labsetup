#!/usr/bin/env python3
"""
Database MSSQL - Instalador simples de SQL Server para Ubuntu (nativo) ou Docker
Instala, configura e testa o SQL Server de forma automatizada.
Uso: sudo python3 mssql_install.py --help
"""

import argparse
import getpass
import os
import secrets
import shutil
import string
import subprocess
import sys
import time


def detect_os():
    """Detecta a distribuição Linux e versão a partir de /etc/os-release."""
    try:
        with open("/etc/os-release") as f:
            content = f.read()
        lower = content.lower()
        version_id = "22.04"
        for line in content.splitlines():
            if line.startswith("VERSION_ID="):
                version_id = line.split("=", 1)[1].strip().strip('"')
                break
        if "ubuntu" in lower:
            return "ubuntu", version_id
        if "debian" in lower:
            return "debian", version_id
        return None, None
    except FileNotFoundError:
        return None, None


def generate_password(length=16):
    """Gera senha aleatória segura compatível com a política do SQL Server."""
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


def run_cmd(cmd, check=True, capture_output=False, env=None):
    """Executa comando com output amigável."""
    print(f"[INFO] Executando: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=True,
        env=env or os.environ.copy(),
    )
    if capture_output:
        return result.stdout.strip()
    return None


def find_sqlcmd():
    """Localiza o binário sqlcmd no sistema."""
    for candidate in (
        shutil.which("sqlcmd"),
        "/opt/mssql-tools18/bin/sqlcmd",
        "/opt/mssql-tools/bin/sqlcmd",
        "/usr/local/bin/sqlcmd",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def configure_firewall():
    """Libera a porta 1433 no firewall usando UFW (preferencial) ou iptables."""
    print("[INFO] Configurando firewall para liberar porta 1433 (SQL Server)...")
    try:
        result = subprocess.run(
            ["ufw", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and "Status: active" in result.stdout:
            run_cmd(["ufw", "allow", "1433/tcp"])
            print("[SUCCESS] Porta 1433 liberada via UFW.")
            return
    except FileNotFoundError:
        pass

    try:
        run_cmd(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", "1433", "-j", "ACCEPT"])
        print("[SUCCESS] Regra adicionada no iptables (lembre-se de persistir se necessário).")
        return
    except Exception:
        pass

    print("[AVISO] Firewall não configurado automaticamente. Libere manualmente a porta 1433/tcp se o firewall estiver ativo.")


def install_mssql_docker(sa_password, container_name="mssql_server", pid="Express"):
    """Instala e inicia o SQL Server em container Docker pronto para produção."""
    if shutil.which("docker") is None:
        print("[ERRO] Docker não encontrado! Instale o Docker primeiro.")
        sys.exit(1)

    print(f"[INFO] Iniciando container SQL Server '{container_name}'...")
    subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)
    run_cmd(["docker", "volume", "create", "mssql_data"])
    run_cmd([
        "docker", "run", "-d",
        "--name", container_name,
        "--restart", "unless-stopped",
        "-e", "ACCEPT_EULA=Y",
        "-e", f"MSSQL_SA_PASSWORD={sa_password}",
        "-e", f"MSSQL_PID={pid}",
        "-p", "1433:1433",
        "-v", "mssql_data:/var/opt/mssql",
        "mcr.microsoft.com/mssql/server:2022-latest",
    ])
    print("[INFO] Aguardando SQL Server inicializar no container...")
    time.sleep(10)
    configure_firewall()
    print(f"[SUCCESS] SQL Server rodando no container '{container_name}' na porta 1433.")


def install_mssql(args, sa_password):
    """Instala SQL Server nativamente no Ubuntu ou via fallback Docker."""
    if getattr(args, "docker", False):
        install_mssql_docker(sa_password, pid=getattr(args, "pid", "Express"))
        return "docker"

    os_type, version_id = detect_os()
    if os_type != "ubuntu":
        print(f"[AVISO] Instalação nativa oficial do SQL Server suporta Ubuntu (detectado: {os_type or 'desconhecido'}).")
        if shutil.which("docker") is not None:
            print("[INFO] Utilizando fallback automático via Docker para SQL Server...")
            install_mssql_docker(sa_password, pid=getattr(args, "pid", "Express"))
            return "docker"
        print("[ERRO] Sistema operacional não suportado para instalação nativa e Docker não encontrado.")
        sys.exit(1)

    supported_ubuntu = version_id if version_id in ("20.04", "22.04", "24.04") else "22.04"
    print(f"[INFO] Ubuntu {version_id} detectado (repositório Microsoft: {supported_ubuntu}).")

    run_cmd(["apt-get", "update", "-y"])
    run_cmd(["apt-get", "install", "-y", "curl", "gnupg", "apt-transport-https"])

    # Adiciona chave GPG e repositório da Microsoft
    run_cmd([
        "bash", "-c",
        "curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg"
    ])
    repo_url = f"https://packages.microsoft.com/config/ubuntu/{supported_ubuntu}/mssql-server-2022.list"
    run_cmd([
        "bash", "-c",
        f"curl -fsSL {repo_url} | sed 's|^deb \\[|deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg |' > /etc/apt/sources.list.d/mssql-server-2022.list"
    ])
    prod_repo = f"https://packages.microsoft.com/config/ubuntu/{supported_ubuntu}/prod.list"
    run_cmd([
        "bash", "-c",
        f"curl -fsSL {prod_repo} > /etc/apt/sources.list.d/mssql-release.list"
    ])

    run_cmd(["apt-get", "update", "-y"])
    run_cmd(["apt-get", "install", "-y", "mssql-server"])

    env = os.environ.copy()
    env["ACCEPT_EULA"] = "Y"
    env["MSSQL_SA_PASSWORD"] = sa_password
    env["MSSQL_PID"] = getattr(args, "pid", "Express")
    run_cmd(["/opt/mssql/bin/mssql-conf", "-n", "setup", "accept-eula"], env=env)

    env_tools = os.environ.copy()
    env_tools["ACCEPT_EULA"] = "Y"
    run_cmd(["apt-get", "install", "-y", "mssql-tools18", "unixodbc-dev"], env=env_tools)

    run_cmd(["systemctl", "enable", "mssql-server"])
    run_cmd(["systemctl", "start", "mssql-server"])
    print("[SUCCESS] SQL Server instalado e serviço iniciado.")

    configure_firewall()
    return "native"


def reset_sa_password_local(sa_password):
    """Redefine a senha do usuário 'sa' localmente usando mssql-conf."""
    print("[INFO] Iniciando reset local da senha do administrador 'sa'...")
    if os.geteuid() != 0:
        print("[ERRO] Para resetar a senha local do SQL Server via mssql-conf, execute com sudo/root.")
        return False

    if not os.path.isfile("/opt/mssql/bin/mssql-conf"):
        print("[ERRO] '/opt/mssql/bin/mssql-conf' não encontrado. O SQL Server está instalado localmente?")
        return False

    try:
        run_cmd(["systemctl", "stop", "mssql-server"])
        env = os.environ.copy()
        env["MSSQL_SA_PASSWORD"] = sa_password
        run_cmd(["/opt/mssql/bin/mssql-conf", "set-sa-password"], env=env)
        run_cmd(["systemctl", "start", "mssql-server"])
        print("[SUCCESS] Senha do usuário 'sa' redefinida com sucesso!")
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao redefinir a senha 'sa': {e}")
        subprocess.run(["systemctl", "start", "mssql-server"], check=False)
        return False


def _run_sa_query(sa_password, database, query, mode="native", container_name="mssql_server"):
    """Executa uma query T-SQL como 'sa' no SQL Server local ou container Docker."""
    if mode == "docker":
        cmd = [
            "docker", "exec",
            "-e", f"SQLCMDPASSWORD={sa_password}",
            container_name,
            "/opt/mssql-tools18/bin/sqlcmd",
            "-S", "localhost",
            "-U", "sa",
            "-d", database,
            "-N", "-C",
            "-b",
            "-Q", query,
        ]
        run_cmd(cmd, check=False)
        return

    sqlcmd_bin = find_sqlcmd()
    if not sqlcmd_bin:
        raise FileNotFoundError("sqlcmd não encontrado após instalação.")

    env = os.environ.copy()
    env["SQLCMDPASSWORD"] = sa_password
    run_cmd(
        [sqlcmd_bin, "-S", "localhost,1433", "-U", "sa", "-d", database, "-N", "-C", "-b", "-Q", query],
        env=env,
        check=False,
    )


def setup_database(args, sa_password, mode="native"):
    """Cria usuário e banco de dados de aplicação no SQL Server."""
    user = args.user or "mssql_app"
    db = args.database or "app_db"
    password = args.password or generate_password()

    esc_user = user.replace("'", "''")
    esc_pwd = password.replace("'", "''")
    esc_db = db.replace("'", "''")

    _run_sa_query(
        sa_password,
        "master",
        (
            f"IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{esc_user}') "
            f"CREATE LOGIN [{user}] WITH PASSWORD = N'{esc_pwd}', CHECK_POLICY = ON;"
        ),
        mode=mode,
    )
    _run_sa_query(
        sa_password,
        "master",
        f"IF DB_ID(N'{esc_db}') IS NULL CREATE DATABASE [{db}];",
        mode=mode,
    )
    _run_sa_query(
        sa_password,
        db,
        (
            f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{esc_user}') "
            f"CREATE USER [{user}] FOR LOGIN [{user}]; "
            f"ALTER ROLE [db_owner] ADD MEMBER [{user}];"
        ),
        mode=mode,
    )

    return user, db, password, sa_password


def test_mssql(user, db, password, host="localhost", port=1433):
    """Testa conexão e funcionamento básico com SQL Server."""
    print(f"[INFO] Testando conexão com SQL Server em {host}:{port}...")
    sqlcmd_bin = find_sqlcmd()
    env = os.environ.copy()
    if password:
        env["SQLCMDPASSWORD"] = password

    try:
        if sqlcmd_bin:
            version = run_cmd(
                [sqlcmd_bin, "-S", f"{host},{port}", "-U", user, "-d", db, "-N", "-C", "-b", "-Q", "SELECT @@VERSION;"],
                env=env,
                capture_output=True,
            )
            print(f"[INFO] Versão: {version.splitlines()[0] if version else 'N/A'}")
            run_cmd(
                [sqlcmd_bin, "-S", f"{host},{port}", "-U", user, "-d", db, "-N", "-C", "-b", "-Q", "SELECT 1 AS test;"],
                env=env,
            )
        elif shutil.which("docker") is not None:
            run_cmd([
                "docker", "run", "--rm", "--network=host",
                "-e", f"SQLCMDPASSWORD={password or ''}",
                "mcr.microsoft.com/mssql-tools:latest",
                "/opt/mssql-tools/bin/sqlcmd",
                "-S", f"{host},{port}", "-U", user, "-d", db, "-N", "-C", "-b", "-Q", "SELECT 1 AS test;",
            ])
        else:
            print("[AVISO] Nem sqlcmd nem docker disponíveis para testar conexão.")
            return False

        print("[SUCCESS] Teste de conexão bem-sucedido! SQL Server está funcionando.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERRO] Falha no teste: {e}")
        return False


def print_credentials(user, password, sa_password=None, host="localhost", port=1433, db=None):
    """Imprime informações de conexão e orientações de acesso externo."""
    print("\n" + "=" * 60)
    print("INFORMAÇÕES DE CONEXÃO DO SQL SERVER (INSTALAÇÃO CONCLUÍDA)")
    print("=" * 60)
    print("1. ADMINISTRADOR DO SISTEMA (SA)")
    print("  Usuário: sa")
    print(f"  Senha:   {sa_password or 'Não informada'}")
    print(f"  Host:    {host}")
    print(f"  Porta:   {port}")
    print("  Banco:   master")
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
    print("     - Porta 1433/tcp liberada no firewall local (UFW/iptables).")
    print("     - Em nuvem (AWS, Azure, GCP, DigitalOcean, etc.), libere 1433/tcp no Security Group.")
    print("  2. Ferramentas Visuais (SSMS, Azure Data Studio, DBeaver, TablePlus):")
    print("     - Escolha SQL Server, informe IP Público, porta 1433 e habilite 'Trust Server Certificate'.")
    print("  3. Via Linha de Comando (CLI):")
    print(f"     sqlcmd -S <IP_PUBLICO>,1433 -U {user} -d {db or 'master'} -N -C")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Instalador simples de SQL Server para Ubuntu (nativo) ou Docker"
    )
    parser.add_argument("--user", default=None, help="Nome do usuário do app (padrão: mssql_app)")
    parser.add_argument("--database", default=None, help="Nome do banco (padrão: app_db)")
    parser.add_argument("--password", default=None, help="Senha do usuário do app")
    parser.add_argument("--sa-password", default=None, help="Senha do administrador 'sa'")
    parser.add_argument("--pid", default="Express", help="Edição SQL Server (Express, Developer, Standard)")
    parser.add_argument("--docker", action="store_true", help="Força instalação via container Docker")
    parser.add_argument("--skip-install", action="store_true", help="Pula a instalação (assume já instalado)")
    parser.add_argument("--reset-passwords", action="store_true", help="Apenas reseta a senha local do usuário 'sa'")
    args, _ = parser.parse_known_args()

    reset_mode = args.reset_passwords
    if len(sys.argv) == 1:
        print("=" * 60)
        print("GERENCIADOR E INSTALADOR SQL SERVER")
        print("=" * 60)
        print("1) Instalar/Configurar SQL Server Completo (Padrão)")
        print("2) Apenas Resetar senha local do administrador 'sa' (mssql-conf)")
        print("=" * 60)
        try:
            opcao = input("Escolha uma opção (1 ou 2, padrão: 1): ").strip()
            if opcao == "2":
                reset_mode = True
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] Cancelado pelo usuário.")
            sys.exit(0)

    user = args.user or "mssql_app"
    db = args.database or "app_db"

    if not args.sa_password:
        senha_sa = getpass.getpass("Senha para o administrador 'sa' (deixe vazio para gerar aleatória): ").strip()
        args.sa_password = senha_sa or generate_password()

    sa_password = args.sa_password

    if reset_mode:
        success = reset_sa_password_local(sa_password)
        if success:
            print_credentials("sa", sa_password, sa_password=sa_password, db="master")
            test_mssql("sa", "master", sa_password)
        else:
            print("[ERRO] Não foi possível reconfigurar a senha do usuário 'sa'.")
            sys.exit(1)
        return

    if not args.password:
        senha_app = getpass.getpass(f"Senha para o usuário do aplicativo '{user}' (deixe vazio para gerar aleatória): ").strip()
        args.password = senha_app or generate_password()

    if os.geteuid() != 0 and not args.skip_install and not args.docker:
        print("[ERRO] Execute como root ou com sudo para instalar pacotes (ou use --docker).")
        sys.exit(1)

    mode = "native"
    if not args.skip_install:
        mode = install_mssql(args, sa_password)

    user, db, password, sa_password = setup_database(args, sa_password, mode=mode)
    test_ok = test_mssql(user, db, password)
    print_credentials(user, password, sa_password=sa_password, db=db)

    if not test_ok:
        print("[AVISO] O teste padrão falhou, mas a instalação pode estar ok. Verifique manualmente.")
        sys.exit(1)


if __name__ == "__main__":
    main()
