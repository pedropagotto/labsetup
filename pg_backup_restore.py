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
import secrets
import string
from pathlib import Path


def generate_random_password(length=16):
    """Gera uma senha segura com letras, números e símbolos."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def extract_roles_from_dump(dump_file, fmt="custom"):
    """Extrai os nomes de roles/usuários referenciados no arquivo de backup."""
    roles = set()
    try:
        if fmt == "custom" and shutil.which("pg_restore") is not None:
            # Lista os conteúdos do dump sem restaurar
            result = subprocess.run(
                ["pg_restore", "-l", dump_file],
                capture_output=True,
                text=True,
                check=False
            )
            for line in result.stdout.splitlines():
                # Linhas com ACL ou GRANT ou OWNER geralmente mencionam a role
                if "ACL" in line or "OWNER TO" in line or "GRANT" in line:
                    parts = line.split()
                    if parts:
                        roles.add(parts[-1])
        else:
            # Para arquivo SQL puro (.sql)
            with open(dump_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "GRANT " in line or "TO " in line or "OWNER TO " in line:
                        parts = line.strip().split()
                        if "TO" in parts:
                            idx = parts.index("TO")
                            if idx + 1 < len(parts):
                                role_name = parts[idx + 1].rstrip(";")
                                if role_name and not role_name.startswith("PUBLIC"):
                                    roles.add(role_name)
    except Exception as e:
        print(f"[AVISO] Não foi possível analisar roles do arquivo de dump: {e}")
    
    # Filtra nomes inválidos/padrão
    roles.discard("postgres")
    roles.discard("PUBLIC")
    return roles


def ensure_roles_exist_on_target(target, roles):
    """Garante a criação prévia de roles/usuários no servidor de restore com senhas aleatórias."""
    if not roles:
        return {}

    created_credentials = {}
    print(f"\n[INFO] Verificando e criando {len(roles)} usuário(s)/role(s) no destino antes do restore: {', '.join(roles)}")

    # Conecta via psql na base 'postgres' (ou target db) para executar CREATE ROLE se não existir
    for role in sorted(roles):
        password = generate_random_password()
        # SQL para criar o usuário se não existir
        sql_script = f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE "{role}" WITH LOGIN PASSWORD '{password}';
                RAISE NOTICE 'Role {role} criada com sucesso.';
            ELSE
                ALTER ROLE "{role}" WITH LOGIN PASSWORD '{password}';
                RAISE NOTICE 'Role {role} já existia. Senha atualizada.';
            END IF;
        END
        $$;
        """
        
        psql_cmd = [
            "-U", target["user"],
            "-h", target.get("host", "localhost"),
            "-p", str(target.get("port", 5432)),
            "-d", "postgres",  # Conecta no DB admin padrão para criar roles globais
            "-c", sql_script
        ]

        try:
            if target["type"] == "docker":
                cmd = build_docker_cmd(target["container_name"], ["psql"] + psql_cmd, target.get("password"))
                run_command(cmd, env=get_pg_env(target.get("password"), target.get("sslmode")), check=False)
            else:
                run_pg_tool("psql", psql_cmd, password=target.get("password"), sslmode=target.get("sslmode"))
            created_credentials[role] = password
        except Exception as e:
            print(f"[AVISO] Falha ao verificar/criar a role '{role}' no destino: {e}")

    return created_credentials


def save_credentials_file(target, credentials, filename="restore_credentials.txt"):
    """Salva um arquivo local com os usuários e senhas gerados para o novo banco de restore."""
    try:
        output_path = Path.cwd() / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("============================================================\n")
            f.write("DATABASE PG - CREDENCIAIS DO BANCO RESTAURADO\n")
            f.write("============================================================\n")
            f.write(f"Host Destino:     {target.get('host')}\n")
            f.write(f"Porta:            {target.get('port')}\n")
            f.write(f"Banco de Dados:   {target.get('database')}\n")
            f.write(f"Usuário Admin:    {target.get('user')}\n")
            f.write("============================================================\n")
            f.write("USUÁRIOS / ROLES CRIADAS/RECONFIGURADAS:\n")
            f.write("============================================================\n")
            if credentials:
                for role, pwd in credentials.items():
                    f.write(f"Usuário: {role}\n")
                    f.write(f"Senha:   {pwd}\n")
                    f.write("-" * 60 + "\n")
            else:
                f.write("Nenhum usuário adicional precisou ser criado.\n")
            f.write("============================================================\n")

        print(f"\n[SUCCESS] Arquivo de credenciais do restore gerado localmente em:\n          {output_path.resolve()}\n")
    except Exception as e:
        print(f"[ERRO] Falha ao salvar arquivo de credenciais: {e}")


def create_pg_user(conn_info=None, target_db=None, username=None, role_type=None):
    """Cria um novo usuário no PostgreSQL com privilégios específicos (Owner, Readonly, Writer)."""
    print("\n" + "=" * 60)
    print("CRIAÇÃO DE NOVO USUÁRIO POSTGRESQL")
    print("=" * 60)

    # 1. Solicita conexões se não fornecidas
    if not conn_info:
        print("Digite os dados de conexão do administrador/superusuário:")
        host = input("1- Host/IP: ").strip() or "localhost"
        port_str = input("2- Porta (padrão 5432): ").strip() or "5432"
        try:
            port = int(port_str)
        except ValueError:
            port = 5432
        user = input("3- Usuário admin (padrão postgres): ").strip() or "postgres"
        password = getpass.getpass("4- Senha admin: ")

        print("5- Usar SSL / Criptografia no PostgreSQL?")
        print("   [1] Sim (Exigido / RDS Aurora / Cloud - sslmode=require)")
        print("   [2] Não (Desativado - sslmode=disable)")
        print("   [3] Opcional (Preferencial - sslmode=prefer)")
        default_opt = "1" if "rds.amazonaws.com" in host else "3"
        ssl_choice = input(f"   Escolha uma opção [1-3] (padrão: {default_opt}): ").strip() or default_opt

        if ssl_choice == "1":
            sslmode = "require"
        elif ssl_choice == "2":
            sslmode = "disable"
        else:
            sslmode = "prefer"

        conn_info = {
            "type": "local",
            "host": host,
            "port": port,
            "user": user,
            "password": password if password else None,
            "sslmode": sslmode
        }

    # 3. Solicita banco de dados
    if not target_db:
        target_db = input("\nNome do banco de dados alvo para conceder privilégios: ").strip()
        while not target_db:
            print("[ERRO] O nome do banco de dados é obrigatório.")
            target_db = input("Nome do banco de dados alvo: ").strip()

    # 4. Solicita nome do usuário
    if not username:
        username = input("Nome do novo usuário a ser criado: ").strip()
        while not username:
            print("[ERRO] O nome do usuário é obrigatório.")
            username = input("Nome do novo usuário: ").strip()

    # 2. Solicita papel do usuário
    if not role_type:
        print(f"\nEscolha o papel (permissões) para o usuário '{username}' no banco '{target_db}':")
        print("  1. Owner    (Acesso total ao banco de dados e proprietário)")
        print("  2. Readonly (Somente leitura - SELECT em tabelas e sequências)")
        print("  3. Writer   (Leitura + Escrita + DDL para criar tabelas/índices; sem DROP de schema/db e sem criar usuários)")
        
        escolha = input("Escolha uma opção [1-3]: ").strip()
        while escolha not in ["1", "2", "3"]:
            print("[ERRO] Opção inválida.")
            escolha = input("Escolha uma opção [1-3]: ").strip()
        
        role_type = "owner" if escolha == "1" else ("readonly" if escolha == "2" else "writer")

    # 8. Gera senha aleatória
    new_password = generate_random_password(16)

    # 5, 6, 7. Monta e executa os scripts SQL conforme a role
    # Primeiro garante que a role/usuário existe
    sql_create_user = f"""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{username}') THEN
            CREATE ROLE "{username}" WITH LOGIN PASSWORD '{new_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
        ELSE
            ALTER ROLE "{username}" WITH LOGIN PASSWORD '{new_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
        END IF;
    END
    $$;
    """

    psql_create_cmd = [
        "-U", conn_info["user"],
        "-h", conn_info.get("host", "localhost"),
        "-p", str(conn_info.get("port", 5432)),
        "-d", "postgres",
        "-c", sql_create_user
    ]

    try:
        run_pg_tool("psql", psql_create_cmd, password=conn_info.get("password"), sslmode=conn_info.get("sslmode"))
    except Exception as e:
        print(f"[ERRO] Falha ao criar a role '{username}': {e}")
        return False

    # Concede privilégios específicos dentro do banco de dados alvo
    sql_grant = ""
    if role_type == "owner":
        # 5. Owner do banco de dados - pode fazer tudo
        sql_grant = f"""
        GRANT ALL PRIVILEGES ON DATABASE "{target_db}" TO "{username}";
        ALTER DATABASE "{target_db}" OWNER TO "{username}";
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{username}";
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{username}";
        GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO "{username}";
        GRANT ALL ON SCHEMA public TO "{username}";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{username}";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{username}";
        """
    elif role_type == "readonly":
        # 6. Readonly - somente leitura
        sql_grant = f"""
        GRANT CONNECT ON DATABASE "{target_db}" TO "{username}";
        GRANT USAGE ON SCHEMA public TO "{username}";
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{username}";
        GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO "{username}";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO "{username}";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO "{username}";
        """
    elif role_type == "writer":
        # 7. Writer - leitura + escrita + DDL no schema public (criar tabelas), sem DROP de schema/db e sem CREATEROLE
        sql_grant = f"""
        GRANT CONNECT ON DATABASE "{target_db}" TO "{username}";
        GRANT USAGE, CREATE ON SCHEMA public TO "{username}";
        GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public TO "{username}";
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{username}";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{username}";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{username}";
        REVOKE DROP ON SCHEMA public FROM "{username}";
        """

    psql_grant_cmd = [
        "-U", conn_info["user"],
        "-h", conn_info.get("host", "localhost"),
        "-p", str(conn_info.get("port", 5432)),
        "-d", target_db,
        "-c", sql_grant
    ]

    try:
        run_pg_tool("psql", psql_grant_cmd, password=conn_info.get("password"), sslmode=conn_info.get("sslmode"))
    except Exception as e:
        print(f"[ERRO] Falha ao atribuir privilégios para '{username}': {e}")
        return False

    # 8. Print no terminal no final
    print("\n" + "=" * 60)
    print("[SUCCESS] USUÁRIO CRIADO E CONFIGURADO COM SUCESSO!")
    print("=" * 60)
    print(f"  Host:            {conn_info.get('host')}")
    print(f"  Porta:           {conn_info.get('port')}")
    print(f"  Banco de Dados:  {target_db}")
    print(f"  Usuário Criado:  {username}")
    print(f"  Senha Gerada:    {new_password}")
    print(f"  Papel/Permissão: {role_type.upper()}")
    print("=" * 60 + "\n")
    return True


def reset_pg_user_password(conn_info=None, target_user=None, new_password=None):
    """Redefine a senha de qualquer usuário existente no PostgreSQL."""
    print("\n" + "=" * 60)
    print("REDEFINIÇÃO DE SENHA DE USUÁRIO POSTGRESQL")
    print("=" * 60)

    # Solicita conexões admin se não fornecidas
    if not conn_info:
        print("Digite os dados de conexão do administrador/superusuário:")
        host = input("1- Host/IP: ").strip() or "localhost"
        port_str = input("2- Porta (padrão 5432): ").strip() or "5432"
        try:
            port = int(port_str)
        except ValueError:
            port = 5432
        user = input("3- Usuário admin (padrão postgres): ").strip() or "postgres"
        password = getpass.getpass("4- Senha admin: ")

        print("5- Usar SSL / Criptografia no PostgreSQL?")
        print("   [1] Sim (Exigido / RDS Aurora / Cloud - sslmode=require)")
        print("   [2] Não (Desativado - sslmode=disable)")
        print("   [3] Opcional (Preferencial - sslmode=prefer)")
        default_opt = "1" if "rds.amazonaws.com" in host else "3"
        ssl_choice = input(f"   Escolha uma opção [1-3] (padrão: {default_opt}): ").strip() or default_opt

        if ssl_choice == "1":
            sslmode = "require"
        elif ssl_choice == "2":
            sslmode = "disable"
        else:
            sslmode = "prefer"

        conn_info = {
            "type": "local",
            "host": host,
            "port": port,
            "user": user,
            "password": password if password else None,
            "sslmode": sslmode
        }

    if not target_user:
        target_user = input("\nNome do usuário PostgreSQL que terá a senha redefinida: ").strip()
        while not target_user:
            print("[ERRO] O nome do usuário é obrigatório.")
            target_user = input("Nome do usuário: ").strip()

    if not new_password:
        opt_pwd = input("Deseja digitar a nova senha ou gerar aleatoriamente? [1=Gerar Aleatória, 2=Digitar Manualmente] (padrão 1): ").strip() or "1"
        if opt_pwd == "2":
            new_password = getpass.getpass("Digite a nova senha: ")
            while not new_password:
                print("[ERRO] Senha não pode ser vazia.")
                new_password = getpass.getpass("Digite a nova senha: ")
        else:
            new_password = generate_random_password(16)

    # Executa o ALTER ROLE no banco
    sql_reset = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{target_user}') THEN
            ALTER ROLE "{target_user}" WITH PASSWORD '{new_password}';
            RAISE NOTICE 'Senha do usuário {target_user} redefinida com sucesso.';
        ELSE
            RAISE EXCEPTION 'O usuário {target_user} não existe no PostgreSQL.';
        END IF;
    END
    $$;
    """

    psql_reset_cmd = [
        "-U", conn_info["user"],
        "-h", conn_info.get("host", "localhost"),
        "-p", str(conn_info.get("port", 5432)),
        "-d", "postgres",
        "-c", sql_reset
    ]

    try:
        run_pg_tool("psql", psql_reset_cmd, password=conn_info.get("password"), sslmode=conn_info.get("sslmode"))
    except Exception as e:
        print(f"[ERRO] Falha ao redefinir a senha do usuário '{target_user}': {e}")
        return False

    print("\n" + "=" * 60)
    print("[SUCCESS] SENHA REDEFINIDA COM SUCESSO!")
    print("=" * 60)
    print(f"  Host:           {conn_info.get('host')}")
    print(f"  Porta:          {conn_info.get('port')}")
    print(f"  Usuário:        {target_user}")
    print(f"  Nova Senha:     {new_password}")
    print("=" * 60 + "\n")
    return True


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


def get_pg_env(password=None, sslmode=None):
    """Retorna cópia do ambiente com PGPASSWORD e PGSSLMODE configurados."""
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    if sslmode:
        env["PGSSLMODE"] = sslmode
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
    """Solicita interativamente os dados de conexão do servidor (host, porta, banco de dados, usuário, senha)."""
    role = "Backup (Origem)" if prefix == "source" else "Restore (Destino)"
    print(f"\n=== Servidor de {role} ===")
    host = input("1- Host/IP: ").strip() or "localhost"
    
    port_str = input("2- Porta (padrão 5432): ").strip() or "5432"
    try:
        port = int(port_str)
    except ValueError:
        port = 5432
        
    db = input("3- Nome do Banco de Dados (Database): ").strip()
    while not db:
        print("[ERRO] Nome do banco de dados é obrigatório.")
        db = input("3- Nome do Banco de Dados (Database): ").strip()

    user = input("4- Usuário (padrão postgres): ").strip() or "postgres"
    password = getpass.getpass("5- Senha: ")
    
    print("6- Usar SSL / Criptografia no PostgreSQL?")
    print("   [1] Sim (Exigido / RDS Aurora / Cloud - sslmode=require)")
    print("   [2] Não (Desativado - sslmode=disable)")
    print("   [3] Opcional (Preferencial - sslmode=prefer)")
    
    default_opt = "1" if "rds.amazonaws.com" in host else "3"
    ssl_choice = input(f"   Escolha uma opção [1-3] (padrão: {default_opt}): ").strip() or default_opt
    
    if ssl_choice == "1":
        sslmode = "require"
    elif ssl_choice == "2":
        sslmode = "disable"
    else:
        sslmode = "prefer"

    return {
        "type": "local",
        "host": host,
        "port": port,
        "database": db,
        "user": user,
        "password": password if password else None,
        "sslmode": sslmode
    }


def prompt_backup_path():
    """Solicita interativamente o path onde salvar o arquivo de backup."""
    print("\n=== Arquivo de Backup ===")
    path = input("Path para salvar o backup: ").strip()
    if not path:
        path = "/tmp/backup.dump"
        print(f"[INFO] Usando path padrão: {path}")
    return path


def run_pg_tool(tool_name, cmd_args, password=None, sslmode=None, input_file=None, output_file=None):
    """
    Executa um comando do Postgres (pg_dump, pg_restore, psql).
    Tenta executar localmente. Se não encontrar o executável local, tenta executar via docker run.
    """
    # 1. Tenta localmente
    if shutil.which(tool_name) is not None:
        cmd = [tool_name] + cmd_args
        env = get_pg_env(password, sslmode)
        if input_file:
            print(f"[INFO] Executando local: {' '.join(cmd)} < {input_file}")
            with open(input_file, "rb") as f_in:
                subprocess.run(cmd, env=env, stdin=f_in, check=True)
        elif output_file:
            print(f"[INFO] Executando local: {' '.join(cmd)} > {output_file}")
            with open(output_file, "wb") as f_out:
                subprocess.run(cmd, env=env, stdout=f_out, check=True)
        else:
            print(f"[INFO] Executando local: {' '.join(cmd)}")
            subprocess.run(cmd, env=env, check=True)
        return

    # 2. Se não tiver local, tenta via docker run
    if shutil.which("docker") is not None:
        print(f"[AVISO] '{tool_name}' não encontrado localmente. Tentando executar via container Docker temporário...")
        docker_cmd = ["docker", "run", "--rm", "-i"]
        if password:
            docker_cmd.extend(["-e", f"PGPASSWORD={password}"])
        if sslmode:
            docker_cmd.extend(["-e", f"PGSSLMODE={sslmode}"])
        
        # Conecta na rede do host para acessar localhost do próprio host de forma transparente
        docker_cmd.append("--network=host")
        docker_cmd.extend(["postgres:latest", tool_name])
        docker_cmd.extend(cmd_args)

        if input_file:
            print(f"[INFO] Executando via Docker: {' '.join(docker_cmd)} < {input_file}")
            with open(input_file, "rb") as f_in:
                subprocess.run(docker_cmd, stdin=f_in, check=True)
        elif output_file:
            print(f"[INFO] Executando via Docker: {' '.join(docker_cmd)} > {output_file}")
            with open(output_file, "wb") as f_out:
                subprocess.run(docker_cmd, stdout=f_out, check=True)
        else:
            print(f"[INFO] Executando via Docker: {' '.join(docker_cmd)}")
            subprocess.run(docker_cmd, check=True)
        return

    raise FileNotFoundError(
        f"Não foi possível encontrar '{tool_name}' localmente nem o comando 'docker' para executar o fallback."
    )


def do_backup(args):
    """Realiza backup usando pg_dump."""
    source = args.source
    backup_file = args.backup_file
    fmt = args.format

    pg_dump_cmd_args = [
        "-U", source["user"],
        "-h", source.get("host", "localhost"),
        "-p", str(source.get("port", 5432)),
        "-d", source["database"],
        "-F", "c" if fmt == "custom" else "p",
        "-b",  # blobs
        "-v"
    ]

    if source["type"] == "docker":
        cmd = build_docker_cmd(source["container_name"], ["pg_dump"] + pg_dump_cmd_args, source.get("password"))
        print(f"[INFO] Backup do container {source['container_name']} para {backup_file}")
        with open(backup_file, "wb") as f:
            env = get_pg_env(source.get("password"), source.get("sslmode"))
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
        run_pg_tool("pg_dump", pg_dump_cmd_args, source.get("password"), sslmode=source.get("sslmode"), output_file=backup_file)

    print(f"[SUCCESS] Backup concluído: {backup_file}")


def do_restore(args):
    """Realiza restore usando pg_restore ou psql."""
    target = args.target
    backup_file = args.backup_file
    fmt = args.format

    # 1. Analisa os usuários/roles referenciados no backup e cria no servidor de restore se não existirem
    roles = extract_roles_from_dump(backup_file, fmt)
    credentials = {}
    if roles:
        credentials = ensure_roles_exist_on_target(target, roles)

    # 2. Executa o Restore
    if fmt == "custom":
        pg_restore_cmd_args = [
            "-U", target["user"],
            "-h", target.get("host", "localhost"),
            "-p", str(target.get("port", 5432)),
            "-d", target["database"],
            "-v",
            "--clean",
            "--if-exists",
            "--no-owner"  # Ignora donos do banco original mantendo permissões gerais
        ]
        if target["type"] == "docker":
            cmd = build_docker_cmd(target["container_name"], ["pg_restore"] + pg_restore_cmd_args + [backup_file], target.get("password"))
            run_command(cmd, env=get_pg_env(target.get("password"), target.get("sslmode")))
        else:
            try:
                run_pg_tool("pg_restore", pg_restore_cmd_args, target.get("password"), sslmode=target.get("sslmode"), input_file=backup_file)
            except subprocess.CalledProcessError as e:
                print(f"[AVISO] pg_restore finalizado com avisos de compatibilidade.")
    else:
        # plain SQL - usa psql
        psql_cmd_args = [
            "-U", target["user"],
            "-h", target.get("host", "localhost"),
            "-p", str(target.get("port", 5432)),
            "-d", target["database"],
            "-v"
        ]
        if target["type"] == "docker":
            cmd = build_docker_cmd(target["container_name"], ["psql"] + psql_cmd_args + ["-f", backup_file], target.get("password"))
            run_command(cmd, env=get_pg_env(target.get("password"), target.get("sslmode")))
        else:
            run_pg_tool("psql", psql_cmd_args, target.get("password"), sslmode=target.get("sslmode"), input_file=backup_file)

    # 3. Salva o arquivo de credenciais local ao finalizar
    save_credentials_file(target, credentials)
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



def run_interactive():
    print("=" * 60)
    print("DATABASE PG - MIGRAÇÃO, BACKUP E GERENCIAMENTO DE USUÁRIOS")
    print("=" * 60)
    print("Escolha o método/operação:")
    print("  1. Backup de Servidor Remoto/Físico para Arquivo Local + Restore (2 etapas)")
    print("  2. Backup + Restore Direto entre Servidores (Físicos, RDS/Aurora, VPS, etc.)")
    print("  3. Migração envolvendo Docker Container")
    print("  4. Criar usuário com permissões (Owner, Readonly, Writer)")
    print("  5. Redefinir senha de usuário PostgreSQL")
    print("=" * 60)
    try:
        escolha = input("Escolha uma opção [1-5]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[INFO] Operação cancelada.")
        sys.exit(0)

    if escolha not in ["1", "2", "3", "4", "5"]:
        print("[ERRO] Opção inválida.")
        sys.exit(1)

    def prompt_conn_docker(role):
        print(f"\n--- Dados de Conexão do PostgreSQL (Container Docker de {role}) ---")
        container = input("Nome do container Docker: ").strip()
        while not container:
            print("[ERRO] Nome do container é obrigatório.")
            container = input("Nome do container Docker: ").strip()
            
        db = input("Nome do banco de dados: ").strip()
        while not db:
            print("[ERRO] Nome do banco de dados é obrigatório.")
            db = input("Nome do banco de dados é obrigatório.")
            
        user = input("Usuário (padrão: postgres): ").strip() or "postgres"
        password = getpass.getpass("Senha: ")
        
        return {
            "type": "docker",
            "container_name": container,
            "host": "localhost",
            "port": 5432,
            "database": db,
            "user": user,
            "password": password if password else None
        }

    def prompt_conn_physical(role):
        return prompt_connection_details("source" if role == "Origem" else "target")

    args = argparse.Namespace()
    args.format = "custom"

    if escolha == "1":
        # 2 etapas bare-metal / remoto
        args.command = "backup"
        args.source = prompt_conn_physical("Origem")
        args.backup_file = prompt_backup_path()
        print("\n[INFO] Iniciando Etapa 1/2: Gerando arquivo de backup...")
        do_backup(args)
        
        args.command = "restore"
        args.target = prompt_conn_physical("Destino")
        print("\n[INFO] Iniciando Etapa 2/2: Restaurando no servidor de destino...")
        do_restore(args)
        
        args.func = lambda x: print("\n[SUCCESS] Migração em duas etapas concluída com sucesso!")

    elif escolha == "2":
        # Direto / Streaming entre servidores físicos/remotos
        args.command = "backup-restore"
        args.source = prompt_conn_physical("Origem")
        args.target = prompt_conn_physical("Destino")
        args.func = do_backup_restore

    elif escolha == "3":
        print("\nConfiguração de Docker:")
        s_type = input("Origem é Docker? (s/N): ").strip().lower()
        args.source = prompt_conn_docker("Origem") if s_type in ("s", "sim", "y", "yes") else prompt_conn_physical("Origem")
        
        t_type = input("Destino é Docker? (s/N): ").strip().lower()
        args.target = prompt_conn_docker("Destino") if t_type in ("s", "sim", "y", "yes") else prompt_conn_physical("Destino")

        args.command = "backup-restore"
        args.func = do_backup_restore

    elif escolha == "4":
        args.command = "create-user"
        args.func = lambda x: create_pg_user()

    elif escolha == "5":
        args.command = "reset-user-password"
        args.func = lambda x: reset_pg_user_password()

    return args



def main():
    if len(sys.argv) == 1:
        args = run_interactive()
        args.func(args)
        return

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

