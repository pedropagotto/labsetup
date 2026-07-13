#!/usr/bin/env python3
"""
Database PG - Configurador de Certificados SSL Let's Encrypt no Kamal
Gera configurações prontas e automatizadas de SSL via Let's Encrypt para o Kamal 1 (Traefik) e Kamal 2 (Kamal Proxy).
Permite configurar e compartilhar o SSL entre múltiplas aplicações de forma robusta.
Uso: python kamal_ssl_config.py --help
"""

import argparse
import os
from pathlib import Path


def generate_kamal1_config(service_name, domain, email, container_port, registry_user):
    """Gera o template de configuração YAML do Kamal 1 (Traefik) para Let's Encrypt."""
    return f"""# ==============================================================================
# CONFIGURAÇÃO SSL LET'S ENCRYPT PARA KAMAL 1 (TRAEFIK)
# ==============================================================================
# Copie e adapte esta configuração no seu arquivo 'config/deploy.yml'
#
# COMO FUNCIONA O COMPARTILHAMENTO DE SSL ENTRE MÚLTIPLAS APLICAÇÕES:
# 1. Traefik roda como um container global único por servidor.
# 2. A primeira aplicação que subir com o bloco 'traefik:' irá inicializar o Traefik 
#    com o resolvedor Let's Encrypt e mapeamento de portas.
# 3. As demais aplicações no mesmo servidor NÃO precisam do bloco 'traefik:' completo.
#    Elas precisam apenas declarar suas próprias 'labels' apontando para o entrypoint 'websecure'
#    e o certresolver 'letsencrypt'. O Traefik irá gerar os certificados para todas de forma dinâmica!
# ==============================================================================

service: {service_name}
image: {registry_user}/{service_name}

servers:
  web:
    hosts:
      - 192.168.1.100  # SUBSTITUA pelo IP público do seu servidor
    labels:
      # Configura o roteamento seguro e a geração automatizada do certificado SSL
      traefik.http.routers.{service_name}-web.entrypoints: websecure
      traefik.http.routers.{service_name}-web.rule: Host(`{domain}`)
      traefik.http.routers.{service_name}-web.tls.certresolver: letsencrypt
      # Porta em que a sua aplicação escuta DENTRO do container Docker (ex: 80, 3000, 8080)
      traefik.http.services.{service_name}-web.loadbalancer.server.port: {container_port}

# Configuração global do Traefik reverse proxy
traefik:
  options:
    publish:
      - "443:443"  # Mapeia a porta HTTPS externa para o Traefik
    volume:
      # Armazena os certificados gerados para que não se percam em reinicializações
      - "/letsencrypt/acme.json:/letsencrypt/acme.json"
  args:
    # Cria as portas de entrada de tráfego HTTP e HTTPS
    entryPoints.web.address: ":80"
    entryPoints.websecure.address: ":443"
    
    # Redirecionamento automático e permanente de todo tráfego HTTP para HTTPS
    entryPoints.web.http.redirections.entryPoint.to: websecure
    entryPoints.web.http.redirections.entryPoint.scheme: https
    entryPoints.web.http.redirections.entrypoint.permanent: true
    
    # Configura o protocolo ACME do Let's Encrypt para validação via desafio HTTP
    certificatesResolvers.letsencrypt.acme.email: "{email}"
    certificatesResolvers.letsencrypt.acme.storage: "/letsencrypt/acme.json"
    certificatesResolvers.letsencrypt.acme.httpchallenge: true
    certificatesResolvers.letsencrypt.acme.httpchallenge.entrypoint: web
"""


def generate_kamal2_config(service_name, domain, container_port, registry_user):
    """Gera o template de configuração YAML do Kamal 2 (Kamal Proxy) para Let's Encrypt."""
    return f"""# ==============================================================================
# CONFIGURAÇÃO SSL LET'S ENCRYPT PARA KAMAL 2 (KAMAL PROXY)
# ==============================================================================
# Copie e adapte esta configuração no seu arquivo 'config/deploy.yml'
#
# COMO FUNCIONA O COMPARTILHAMENTO DE SSL ENTRE MÚLTIPLAS APLICAÇÕES:
# 1. Kamal 2 substitui o Traefik pelo Kamal Proxy nativo.
# 2. O Kamal Proxy suporta nativamente múltiplas aplicações por servidor.
# 3. Basta habilitar 'ssl: true' e informar o 'host' em cada uma das aplicações (deploy.yml).
#    O Kamal Proxy irá obter e gerenciar de forma automática e independente os certificados SSL 
#    Let's Encrypt para cada domínio associado a cada container!
# ==============================================================================

service: {service_name}
image: {registry_user}/{service_name}

servers:
  web:
    - 192.168.1.100  # SUBSTITUA pelo IP público do seu servidor

# Kamal Proxy configura SSL nativo para cada aplicação com extrema simplicidade
proxy:
  ssl: true          # Ativa o Let's Encrypt automático via Kamal Proxy
  host: {domain}     # Domínio que apontará para esta aplicação
  app_port: {container_port}  # Porta em que sua aplicação escuta dentro do container (ex: 80, 3000, 8080)
"""


def generate_kamal1_hook_script():
    """Gera o script do hook 'docker-setup' para configurar as permissões corretas no servidor remoto."""
    return """#!/bin/sh
# ==============================================================================
# KAMAL HOOK: docker-setup
# Localização: .kamal/hooks/docker-setup (deve ser executável: chmod +x)
#
# Este hook roda automaticamente no Kamal 1 antes de inicializar o Docker.
# Ele cria a estrutura de arquivos para o Let's Encrypt com as permissões corretas
# requeridas pelo Traefik (permissão estrita chmod 600 em acme.json).
# ==============================================================================

echo "[HOOK] Inicializando estrutura do Let's Encrypt com permissões seguras..."

for host in $(echo $KAMAL_HOSTS | sed "s/,/ /g")
do
  echo "Configurando servidor: $host"
  ssh root@$host 'mkdir -p /letsencrypt && touch /letsencrypt/acme.json && chmod 600 /letsencrypt/acme.json'
done

echo "[HOOK] Estrutura Let's Encrypt criada com sucesso!"
"""


def setup_ssl_config(version, service_name, domain, email, container_port, registry_user, output_dir=None):
    """Executa a rotina de criação das configurações do Kamal com SSL Let's Encrypt."""
    out_path = Path(output_dir) if output_dir else Path.cwd()
    out_path.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print(f"GERANDO CONFIGURAÇÃO SSL LET'S ENCRYPT PARA KAMAL {version}")
    print("=" * 60)
    print(f"  Serviço:      {service_name}")
    print(f"  Domínio:      {domain}")
    print(f"  Porta Interna:{container_port}")
    if version == 1:
        print(f"  Email ACME:   {email}")
    print("=" * 60 + "\n")

    if version == 1:
        # 1. Config de deploy
        yaml_content = generate_kamal1_config(service_name, domain, email, container_port, registry_user)
        deploy_file = out_path / "deploy.kamal1.example.yml"
        with open(deploy_file, "w", encoding="utf-8") as f:
            f.write(yaml_content)
        print(f"[SUCCESS] Arquivo de configuração de exemplo criado: {deploy_file}")

        # 2. Hook do docker-setup
        hooks_dir = out_path / ".kamal" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_file = hooks_dir / "docker-setup"
        
        with open(hook_file, "w", encoding="utf-8") as f:
            f.write(generate_kamal1_hook_script())
        
        try:
            # Tenta dar permissão de execução
            os.chmod(hook_file, 0o755)
            print(f"[SUCCESS] Hook de configuração criado e marcado como executável: {hook_file}")
        except Exception as e:
            print(f"[AVISO] Não foi possível dar permissão de execução ao hook automaticamente: {e}")
            print(f"        Por favor execute: chmod +x {hook_file}")

        print("\n[INFO] DICA PARA COMPARTILHAR SSL COM MAIS APLICAÇÕES:")
        print("  - Ao implantar outra aplicação no mesmo servidor, não inclua o bloco 'traefik:' nela.")
        print("  - Basta que as demais aplicações configurem suas próprias 'labels' sob 'servers.web.labels'")
        print("    apontando para o entrypoint 'websecure' e o resolvedor 'letsencrypt'.")

    else:
        # Kamal 2
        yaml_content = generate_kamal2_config(service_name, domain, container_port, registry_user)
        deploy_file = out_path / "deploy.kamal2.example.yml"
        with open(deploy_file, "w", encoding="utf-8") as f:
            f.write(yaml_content)
        print(f"[SUCCESS] Arquivo de configuração de exemplo criado: {deploy_file}")

        print("\n[INFO] DICA PARA COMPARTILHAR SSL COM MAIS APLICAÇÕES NO KAMAL 2:")
        print("  - No Kamal 2, o Kamal Proxy gerencia automaticamente o SSL para cada aplicação.")
        print("  - Basta repetir o bloco 'proxy' em cada um dos arquivos 'deploy.yml' de suas aplicações,")
        print("    ajustando o 'host' para o domínio correspondente a cada serviço.")

    print("\n" + "=" * 60)
    print("CONFIGURAÇÃO SSL CONCLUÍDA COM SUCESSO!")
    print("=" * 60 + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Gerador de configuração SSL Let's Encrypt para Kamal 1 e Kamal 2"
    )
    parser.add_argument("--kamal-version", type=int, choices=[1, 2], default=2, help="Versão do Kamal (1 ou 2)")
    parser.add_argument("--service", default=None, help="Nome do serviço/aplicação")
    parser.add_argument("--domain", default=None, help="Domínio para o certificado SSL")
    parser.add_argument("--email", default=None, help="E-mail de contato para o Let's Encrypt (Kamal 1)")
    parser.add_argument("--port", type=int, default=None, help="Porta interna do container")
    parser.add_argument("--registry-user", default="username", help="Nome de usuário do Docker Registry")
    parser.add_argument("--output-dir", default=None, help="Diretório onde as configurações serão criadas")
    args, unknown = parser.parse_known_args()

    # Se estiver rodando interativamente (sem argumentos de preenchimento de campos principais)
    is_interactive = not (args.service or args.domain)

    version = args.kamal_version
    if is_interactive:
        print("\n" + "=" * 60)
        print("CONFIGURADOR DE SSL LET'S ENCRYPT PARA O KAMAL")
        print("=" * 60)
        try:
            v_input = input("Escolha a versão do Kamal [1 ou 2] (padrão: 2): ").strip()
            if v_input in ("1", "2"):
                version = int(v_input)
        except (EOFError, KeyboardInterrupt):
            print("\nOperação cancelada.")
            return

    service = args.service
    if not service:
        try:
            service = input("Digite o nome da sua aplicação/serviço (padrão: app_web): ").strip()
            if not service:
                service = "app_web"
        except (EOFError, KeyboardInterrupt):
            print("\nOperação cancelada.")
            return

    domain = args.domain
    if not domain:
        try:
            domain = input("Digite o domínio ou subdomínio (ex: app.meusite.com): ").strip()
            while not domain:
                domain = input("[ERRO] Domínio é obrigatório. Digite o domínio: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOperação cancelada.")
            return

    email = args.email
    if version == 1 and not email:
        try:
            email = input("Digite o e-mail de contato para o Let's Encrypt (ex: admin@meusite.com): ").strip()
            while not email:
                email = input("[ERRO] E-mail é obrigatório para Kamal 1. Digite o e-mail: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOperação cancelada.")
            return

    port = args.port
    if not port:
        default_port = 3000 if version == 1 else 80
        try:
            port_input = input(f"Digite a porta interna do container da aplicação (padrão: {default_port}): ").strip()
            if port_input:
                port = int(port_input)
            else:
                port = default_port
        except (EOFError, KeyboardInterrupt):
            print("\nOperação cancelada.")
            return
        except ValueError:
            print(f"[AVISO] Entrada inválida. Usando porta padrão {default_port}.")
            port = default_port

    setup_ssl_config(
        version=version,
        service_name=service,
        domain=domain,
        email=email,
        container_port=port,
        registry_user=args.registry_user,
        output_dir=args.output_dir
    )


if __name__ == "__main__":
    main()
