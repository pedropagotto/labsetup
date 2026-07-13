#!/usr/bin/env python3
"""
Database PG - Instalador de Portainer CE para Debian/Ubuntu
Instala e configura o Portainer CE (Community Edition) de forma automatizada no Docker.
Uso: sudo python portainer_install.py --help
"""

import argparse
import os
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


def is_docker_installed():
    """Verifica se o Docker está instalado e acessível."""
    try:
        # Tenta executar docker --version para verificar se o binário existe
        subprocess.run(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def is_docker_running():
    """Verifica se o serviço do Docker está em execução."""
    try:
        # Tenta executar docker info para garantir que o daemon esteja ativo
        subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def install_portainer(skip_install=False):
    """Instala o Portainer CE no Docker."""
    if skip_install:
        print("[INFO] Pulando instalação física do Portainer (--skip-install).")
        return True

    # Verifica se o Docker está instalado e em execução
    if not is_docker_installed():
        print("[ERRO] Docker não encontrado! Por favor, instale o Docker primeiro (opção 3 do menu).")
        return False

    if not is_docker_running():
        print("[ERRO] O serviço do Docker não está em execução! Inicie o Docker e tente novamente.")
        return False

    print("[INFO] Iniciando instalação do Portainer CE Opensource...")

    # Verifica se o container portainer já existe
    container_exists = False
    try:
        check_container = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=^/portainer$", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True
        )
        if "portainer" in check_container.stdout:
            container_exists = True
    except subprocess.CalledProcessError as e:
        print(f"[AVISO] Não foi possível verificar se o container portainer já existe: {e}")

    if container_exists:
        print("[INFO] Um container chamado 'portainer' já existe. Parando e removendo para reinstalação limpa...")
        try:
            run_cmd(["docker", "stop", "portainer"], check=False)
            run_cmd(["docker", "rm", "portainer"], check=False)
            print("[SUCCESS] Container antigo 'portainer' removido.")
        except Exception as e:
            print(f"[ERRO] Falha ao remover container portainer existente: {e}")
            return False

    # Cria o volume de dados se não existir
    print("[INFO] Criando volume docker 'portainer_data' para persistência de dados...")
    try:
        run_cmd(["docker", "volume", "create", "portainer_data"])
    except subprocess.CalledProcessError as e:
        print(f"[ERRO] Falha ao criar volume docker: {e}")
        return False

    # Executa o container Portainer CE
    print("[INFO] Baixando e iniciando o container do Portainer CE...")
    try:
        # Mapeia portas 8000 (tunnel), 9443 (HTTPS), e 9000 (HTTP, opcional/legado para facilidade de desenvolvimento)
        run_cmd([
            "docker", "run", "-d",
            "-p", "8000:8000",
            "-p", "9000:9000",
            "-p", "9443:9443",
            "--name", "portainer",
            "--restart", "always",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            "-v", "portainer_data:/data",
            "portainer/portainer-ce:latest"
        ])
    except subprocess.CalledProcessError as e:
        print(f"[ERRO] Falha ao iniciar o container do Portainer: {e}")
        return False

    print("\n" + "=" * 60)
    print("[SUCCESS] PORTAINER CE INSTALADO COM SUCESSO!")
    print("=" * 60)
    print("O Portainer CE está sendo executado em segundo plano.")
    print("Você pode acessá-lo através do seu navegador:")
    print("  - HTTPS: https://<IP_DO_SERVIDOR>:9443")
    print("  - HTTP:  http://<IP_DO_SERVIDOR>:9000")
    print("============================================================\n")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Instalador de Portainer CE para Debian/Ubuntu"
    )
    parser.add_argument("--skip-install", action="store_true", help="Pula a instalação real do Portainer")
    args, unknown = parser.parse_known_args()

    # O Portainer é executado via Docker, por isso geralmente precisa de privilégios sudo/root se o usuário logado não estiver no grupo docker.
    # No entanto, se skip_install for True, não é necessário.
    if os.geteuid() != 0 and not args.skip_install:
        print("[ERRO] Execute como root ou com sudo para garantir o acesso ao Docker daemon.")
        sys.exit(1)

    success = install_portainer(skip_install=args.skip_install)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
