#!/usr/bin/env python3
"""
Database PG - Ferramenta Principal All-in-One (Main Tool)
Permite escolher qual operação executar: Backup/Restore, Instalação do PostgreSQL,
Instalação do Docker, Instalação do Kamal ou Instalação Completa All-in-One.
Uso: python pg_main.py
"""

import subprocess
import sys
from pathlib import Path


def filter_args(args):
    """Filtra argumentos de controle principais para não passar aos sub-scripts."""
    if args is None:
        return []
    control_args = {
        "--all", "--install-all", "-aio",
        "--postgres", "--install-postgres",
        "--docker", "--install-docker",
        "--kamal", "--install-kamal",
        "--portainer", "--install-portainer",
        "--kamal-ssl", "--config-kamal-ssl",
        "--reset-passwords", "--reset-password"
    }
    return [arg for arg in args if arg not in control_args]


def print_menu():
    """Exibe o menu principal de opções."""
    print("\n" + "=" * 60)
    print("DATABASE PG - FERRAMENTA PRINCIPAL ALL-IN-ONE")
    print("=" * 60)
    print("Escolha a operação que deseja executar:")
    print("  1. Backup / Restore de PostgreSQL")
    print("  2. Instalar PostgreSQL completo pronto para produção")
    print("  3. Instalar Docker CE (Debian/Ubuntu)")
    print("  4. Instalar Kamal (Debian/Ubuntu)")
    print("  5. Instalar Portainer CE (Debian/Ubuntu)")
    print("  6. Instalação Completa All-in-One (PostgreSQL + Docker + Kamal + Portainer)")
    print("  7. Configurar SSL Let's Encrypt no Kamal (Compartilhável)")
    print("  8. Recuperar / Resetar senhas locais de usuários PostgreSQL (via sudo/peer)")
    print("  9. Criar novo usuário PostgreSQL (Owner, Readonly, Writer)")
    print(" 10. Redefinir senha de um usuário PostgreSQL (Remoto / RDS / Bare-metal)")
    print("  0. Sair")
    print("=" * 60)


def run_backup_restore(extra_args=None):
    """Executa o script de backup/restore."""
    script_path = Path(__file__).parent / "pg_backup_restore.py"
    if not script_path.exists():
        print("[ERRO] pg_backup_restore.py não encontrado!")
        return False

    print("\n[INFO] Iniciando ferramenta de Backup/Restore...")
    print("[INFO] Use --help para ver as opções de subcomandos (backup, restore, backup-restore)\n")

    args = extra_args if extra_args is not None else sys.argv[1:]
    cmd = [sys.executable, str(script_path)] + filter_args(args)
    try:
        subprocess.run(cmd, check=False)
        return True
    except KeyboardInterrupt:
        print("\n[INFO] Operação interrompida pelo usuário.")
        return False


def run_create_user(extra_args=None):
    """Executa o script de criação de usuários no PostgreSQL."""
    script_path = Path(__file__).parent / "pg_backup_restore.py"
    if not script_path.exists():
        print("[ERRO] pg_backup_restore.py não encontrado!")
        return False

    print("\n[INFO] Iniciando ferramenta de Criação de Usuários PostgreSQL...\n")

    import pg_backup_restore
    return pg_backup_restore.create_pg_user()


def run_reset_user_password(extra_args=None):
    """Executa o script de redefinição de senha de usuários do PostgreSQL (Remoto / Físico / Cloud)."""
    script_path = Path(__file__).parent / "pg_backup_restore.py"
    if not script_path.exists():
        print("[ERRO] pg_backup_restore.py não encontrado!")
        return False

    print("\n[INFO] Iniciando ferramenta de Redefinição de Senha de Usuários...\n")

    import pg_backup_restore
    return pg_backup_restore.reset_pg_user_password()


def run_install(extra_args=None):
    """Executa o script de instalação do PostgreSQL."""
    script_path = Path(__file__).parent / "pg_install.py"
    if not script_path.exists():
        print("[ERRO] pg_install.py não encontrado!")
        return False

    print("\n[INFO] Iniciando instalador do PostgreSQL...")
    print("[AVISO] Esta operação geralmente requer sudo/root.\n")

    args = extra_args if extra_args is not None else sys.argv[1:]
    cmd = [sys.executable, str(script_path)] + filter_args(args)
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode == 0
    except KeyboardInterrupt:
        print("\n[INFO] Operação interrompida pelo usuário.")
        return False


def run_reset_passwords(extra_args=None):
    """Executa o script de instalação do PostgreSQL no modo de reset de senhas."""
    script_path = Path(__file__).parent / "pg_install.py"
    if not script_path.exists():
        print("[ERRO] pg_install.py não encontrado!")
        return False

    print("\n[INFO] Iniciando reconfiguração de senhas do PostgreSQL...")
    print("[AVISO] Esta operação pode requerer sudo/root se o acesso peer estiver bloqueado.\n")

    args = extra_args if extra_args is not None else sys.argv[1:]
    cmd = [sys.executable, str(script_path), "--reset-passwords"] + filter_args(args)
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode == 0
    except KeyboardInterrupt:
        print("\n[INFO] Operação interrompida pelo usuário.")
        return False


def run_docker_install(extra_args=None, skip_reboot=False):
    """Executa o script de instalação do Docker."""
    script_path = Path(__file__).parent / "docker_install.py"
    if not script_path.exists():
        print("[ERRO] docker_install.py não encontrado!")
        return False

    print("\n[INFO] Iniciando instalador do Docker...")
    print("[AVISO] Esta operação requer sudo/root.\n")

    args = extra_args if extra_args is not None else sys.argv[1:]
    filtered = filter_args(args)
    # Se for All-in-One, precisamos passar --no-reboot
    if skip_reboot and "--no-reboot" not in filtered:
        filtered.append("--no-reboot")

    cmd = [sys.executable, str(script_path)] + filtered
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode == 0
    except KeyboardInterrupt:
        print("\n[INFO] Operação interrompida pelo usuário.")
        return False


def run_kamal_install(extra_args=None):
    """Executa o script de instalação do Kamal."""
    script_path = Path(__file__).parent / "kamal_install.py"
    if not script_path.exists():
        print("[ERRO] kamal_install.py não encontrado!")
        return False

    print("\n[INFO] Iniciando instalador do Kamal...")
    print("[AVISO] Esta operação requer sudo/root.\n")

    args = extra_args if extra_args is not None else sys.argv[1:]
    cmd = [sys.executable, str(script_path)] + filter_args(args)
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode == 0
    except KeyboardInterrupt:
        print("\n[INFO] Operação interrompida pelo usuário.")
        return False


def run_portainer_install(extra_args=None):
    """Executa o script de instalação do Portainer."""
    script_path = Path(__file__).parent / "portainer_install.py"
    if not script_path.exists():
        print("[ERRO] portainer_install.py não encontrado!")
        return False

    print("\n[INFO] Iniciando instalador do Portainer CE...")
    print("[AVISO] Esta operação requer sudo/root.\n")

    args = extra_args if extra_args is not None else sys.argv[1:]
    cmd = [sys.executable, str(script_path)] + filter_args(args)
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode == 0
    except KeyboardInterrupt:
        print("\n[INFO] Operação interrompida pelo usuário.")
        return False


def run_kamal_ssl_config(extra_args=None):
    """Executa o configurador SSL para o Kamal."""
    script_path = Path(__file__).parent / "kamal_ssl_config.py"
    if not script_path.exists():
        print("[ERRO] kamal_ssl_config.py não encontrado!")
        return False

    print("\n[INFO] Iniciando configurador SSL do Kamal...")

    args = extra_args if extra_args is not None else sys.argv[1:]
    cmd = [sys.executable, str(script_path)] + filter_args(args)
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode == 0
    except KeyboardInterrupt:
        print("\n[INFO] Operação interrompida pelo usuário.")
        return False


def run_all_in_one():
    """Executa a instalação sequencial de todos os componentes (Docker, Kamal, Portainer, PostgreSQL)."""
    print("\n" + "=" * 60)
    print("INICIANDO INSTALAÇÃO COMPLETA ALL-IN-ONE (AIO)")
    print("=" * 60)
    print("Esta operação irá instalar de forma otimizada para produção:")
    print("  1. Docker CE (e configurar seu usuário)")
    print("  2. Ruby e Kamal")
    print("  3. Portainer CE (Interface web de gerenciamento)")
    print("  4. PostgreSQL (banco de dados completo, usuário e teste de conexão)")
    print("=" * 60 + "\n")

    # Passamos sys.argv[1:] para os scripts para preservar flags como --skip-install
    extra_args = sys.argv[1:]

    # Passo 1: Docker (forçando skip de reboot imediato)
    print("\n>>> [PASSO 1/4] Instalação do Docker CE...")
    docker_ok = run_docker_install(extra_args=extra_args, skip_reboot=True)
    if not docker_ok:
        print("[ERRO] Falha na instalação do Docker. Abortando instalação All-in-One.")
        return

    # Passo 2: Kamal
    print("\n>>> [PASSO 2/4] Instalação do Kamal...")
    kamal_ok = run_kamal_install(extra_args=extra_args)
    if not kamal_ok:
        print("[ERRO] Falha na instalação do Kamal. Abortando instalação All-in-One.")
        return

    # Passo 3: Portainer CE
    print("\n>>> [PASSO 3/4] Instalação do Portainer CE...")
    portainer_ok = run_portainer_install(extra_args=extra_args)
    if not portainer_ok:
        print("[AVISO] Houve um problema na instalação do Portainer CE.")
        # Não abortamos, pois os anteriores já foram instalados.

    # Passo 4: PostgreSQL
    print("\n>>> [PASSO 4/4] Instalação do PostgreSQL completo...")
    pg_ok = run_install(extra_args=extra_args)
    if not pg_ok:
        print("[AVISO] Houve um problema na instalação ou teste do PostgreSQL.")
        # Não abortamos, pois os anteriores já foram instalados.

    print("\n" + "=" * 60)
    print("[SUCCESS] INSTALAÇÃO COMPLETA ALL-IN-ONE CONCLUÍDA!")
    print("=" * 60)
    print("Todos os componentes (Docker, Kamal, Portainer, PostgreSQL) foram processados.")
    print("============================================================\n")

    # Se o Docker foi instalado, sugere reinicialização no final
    if "--skip-install" not in filter_args(extra_args):
        try:
            confirm = input("Deseja reiniciar o sistema agora para aplicar as permissões do Docker? (s/N): ").strip().lower()
            if confirm in ("s", "sim", "y", "yes"):
                print("[INFO] Reiniciando o sistema em 5 segundos...")
                import time
                time.sleep(5)
                subprocess.run(["systemctl", "reboot"], check=False)
            else:
                print("[INFO] Reinicialização ignorada. Lembre-se de reiniciar manualmente depois.")
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] Reinicialização ignorada.")


def main():
    # Roteamento direto se argumentos de ação forem passados pela CLI
    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        if first_arg in ("--install-postgres", "--postgres"):
            run_install(sys.argv[2:])
            return
        elif first_arg in ("--install-docker", "--docker"):
            run_docker_install(sys.argv[2:])
            return
        elif first_arg in ("--install-kamal", "--kamal"):
            run_kamal_install(sys.argv[2:])
            return
        elif first_arg in ("--install-portainer", "--portainer"):
            run_portainer_install(sys.argv[2:])
            return
        elif first_arg in ("--config-kamal-ssl", "--kamal-ssl"):
            run_kamal_ssl_config(sys.argv[2:])
            return
        elif first_arg in ("--reset-passwords", "--reset-password"):
            run_reset_passwords(sys.argv[2:])
            return
        elif first_arg in ("--install-all", "--all", "-aio"):
            run_all_in_one()
            return
        elif first_arg in ("--backup-restore", "--backup", "--restore", "backup", "restore"):
            # Repassa tudo para o backup_restore
            run_backup_restore(sys.argv[1:])
            return

    # Caso contrário, exibe o menu interativo
    while True:
        print_menu()
        try:
            choice = input("Digite sua escolha [0-10]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSaindo...")
            break

        if choice == "1":
            run_backup_restore()
        elif choice == "2":
            run_install()
        elif choice == "3":
            run_docker_install()
        elif choice == "4":
            run_kamal_install()
        elif choice == "5":
            run_portainer_install()
        elif choice == "6":
            run_all_in_one()
        elif choice == "7":
            run_kamal_ssl_config()
        elif choice == "8":
            run_reset_passwords()
        elif choice == "9":
            run_create_user()
        elif choice == "10":
            run_reset_user_password()
        elif choice == "0":
            print("Saindo da ferramenta principal. Até logo!")
            break
        else:
            print("[ERRO] Opção inválida. Tente novamente.")


if __name__ == "__main__":
    main()
