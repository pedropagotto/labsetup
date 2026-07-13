# Database PG - Backup e Restore para PostgreSQL

Projeto simples em Python para facilitar backups e restores de bancos de dados PostgreSQL, suportando cenários com Docker e servidores bare-metal.

## Objetivo
- Portátil: pode ser copiado e executado em qualquer máquina com Python 3.
- Suporta 3 cenários principais:
  1. Backup de container Docker → arquivo local → Restore em servidor PostgreSQL sem container.
  2. Backup de container Docker → Restore direto em outro container Docker.
  3. Backup de servidor PostgreSQL sem container → Restore em outro servidor sem container.

## Ferramenta Principal All-in-One (pg_main.py)
O script `pg_main.py` é o entrypoint principal da ferramenta unificada. Ele permite escolher interativamente qual operação executar ou acionar as ações diretamente via argumentos de linha de comando.

Para maior facilidade e rapidez, o projeto conta com suporte a **Make**. Para iniciar o menu interativo de escolha, basta executar:

```bash
make start
```

Ou de forma tradicional:

```bash
python3 pg_main.py
```

### Comandos de Atalho (Makefile):
Se preferir, utilize os comandos simplificados via `make` para agilizar a execução de tarefas comuns:
- `make start` : Inicia o menu interativo (`pg_main.py`).
- `make install-postgres` : Executa o instalador do PostgreSQL (requer sudo).
- `make install-docker` : Executa o instalador do Docker CE (requer sudo).
- `make install-kamal` : Executa o instalador do Kamal (requer sudo).
- `make install-portainer` : Executa o instalador do Portainer CE (requer sudo).
- `make config-kamal-ssl` : Gera templates de configuração de SSL Let's Encrypt para o Kamal.
- `make install-all` : Executa o instalador All-in-One completo (requer sudo).
- `make backup-restore` : Executa a ferramenta de Backup/Restore.
- `make help` : Exibe a lista de comandos do Makefile disponíveis.

### Menu Interativo:
- `1` → **Backup / Restore de PostgreSQL** (`pg_backup_restore.py`)
- `2` → **Instalar PostgreSQL** completo pronto para produção (`pg_install.py`)
- `3` → **Instalar Docker CE** de forma otimizada (`docker_install.py`)
- `4` → **Instalar Kamal** via Ruby/gem (`kamal_install.py`)
- `5` → **Instalar Portainer CE** de forma otimizada (`portainer_install.py`)
- `6` → **Instalação Completa All-in-One (AIO)**: Instala e configura Docker, Kamal, Portainer CE e PostgreSQL sequencialmente, realizando testes de conexão e sugerindo reinicialização ao final.
- `7` → **Configurar SSL Let's Encrypt no Kamal** (`kamal_ssl_config.py`): Gera de forma interativa configurações de SSL compartilháveis para Kamal 1 e Kamal 2.
- `0` → **Sair**

### Atalhos via Linha de Comando (CLI):
Para facilitar a automação em servidores limpos (bare-metal ou VPS), você pode chamar as rotinas diretamente passando argumentos:
- `--all` / `--install-all` / `-aio` : Executa o assistente de instalação completo All-in-One.
- `--postgres` / `--install-postgres` : Executa diretamente o instalador do PostgreSQL.
- `--docker` / `--install-docker` : Executa diretamente o instalador do Docker.
- `--kamal` / `--install-kamal` : Executa diretamente o instalador do Kamal.
- `--portainer` / `--install-portainer` : Executa diretamente o instalador do Portainer CE.
- `--kamal-ssl` / `--config-kamal-ssl` : Executa o gerador de configurações SSL para o Kamal.
- `backup` / `restore` / `--backup-restore` : Repassa os argumentos diretamente para a ferramenta de backup e restore.

*Qualquer argumento extra fornecido (ex: `--skip-install`, `--user`, `--password`) será repassado de forma inteligente para os instaladores correspondentes.*

## Instalação do PostgreSQL (Debian/Ubuntu)
O script `pg_install.py` automatiza a instalação completa do PostgreSQL em servidores Debian ou Ubuntu, garantindo que esteja pronto para produção:

```bash
sudo python3 pg_install.py
```

Opções:
- `--user NOME` : nome do usuário do aplicativo (padrão: postgres_app)
- `--database NOME` : nome do banco do aplicativo (padrão: app_db)
- `--password SENHA` : senha customizada do usuário do aplicativo (será solicitada interativamente se omitida; gerada aleatória se deixada vazia)
- `--postgres-password SENHA` : senha customizada do superusuário administrador 'postgres' (será solicitada interativamente se omitida; gerada aleatória se deixada vazia)
- `--skip-install` : pula instalação (útil para configurar apenas usuário/banco)

Ao final, o script:
- Configura de forma robusta e automática o acesso externo do PostgreSQL (ajustando `postgresql.conf` para `listen_addresses = '*'` e adicionando as permissões adequadas em `pg_hba.conf` para IPv4 e IPv6).
- Configura a senha do superusuário administrador `postgres`.
- Imprime de forma estruturada as credenciais de acesso tanto do superusuário `postgres` quanto do usuário do aplicativo (usuário, senha, host, porta, banco).
- Apresenta orientações claras sobre como realizar a conexão externa com o servidor (regras de firewall na nuvem, strings de conexão e comandos CLI).
- Realiza o teste padrão de conexão com `SELECT 1` para confirmar o funcionamento.
- Oferece a opção de executar um **teste de conexão personalizado** (solicitando host, porta, usuário, senha e banco).

**Nota**: Execute sempre com `sudo`. A senha gerada é exibida apenas uma vez.

## Instalação do Docker CE (Debian/Ubuntu)
O script `docker_install.py` instala e configura de forma otimizada para produção o Docker Engine, containerd e plugins do Docker Compose no Debian ou Ubuntu:

```bash
sudo python3 docker_install.py
```

Funcionalidades:
- Detecta a distribuição de forma nativa e adiciona os repositórios oficiais e chaves GPG corretas.
- Solicita interativamente o usuário do sistema (com detecção do usuário que executou o `sudo`) para adicioná-lo aos grupos `docker` e `sudo`, evitando o uso direto do root.
- Gerencia o processo de reboot opcional e amigável.

## Instalação do Kamal (Debian/Ubuntu)
O script `kamal_install.py` automatiza a preparação do ambiente Ruby e instala o Kamal:

```bash
sudo python3 kamal_install.py
```

Funcionalidades:
- Instala a versão completa do Ruby (`ruby-full`) e as ferramentas essenciais de compilação de extensões nativas (`build-essential`, `libssl-dev`, etc.).
- Instala a gem `kamal` de forma global e limpa.

## Instalação do Portainer CE (Debian/Ubuntu)
O script `portainer_install.py` automatiza a instalação do Portainer CE (Community Edition) opensource no Docker:

```bash
sudo python3 portainer_install.py
```

Funcionalidades:
- Verifica se o Docker está instalado e em execução no sistema.
- Gerencia e remove containers antigos do Portainer que possam causar conflitos de nome.
- Cria o volume docker `portainer_data` para persistência de dados.
- Executa o container oficial do Portainer CE mapeando as portas `8000` (túnel TCP), `9000` (HTTP) e `9443` (HTTPS) para fácil acesso.

## Configuração de Certificado SSL Let's Encrypt no Kamal
O script `kamal_ssl_config.py` automatiza e gera configurações robustas de certificados SSL Let's Encrypt para que todas as suas aplicações rodem sob HTTPS de forma simples.

Ele oferece suporte tanto para o **Kamal 1** (utilizando Traefik como Proxy Reverso) quanto para o **Kamal 2** (utilizando o Kamal Proxy nativo).

```bash
python3 kamal_ssl_config.py
```

### Funcionalidades:
- **Suporte Multiversão**: Gera templates completos de `config/deploy.yml` para Kamal 1 e Kamal 2.
- **SSL Automatizado e Gratuito**: Configura os resolvedores ACME do Let's Encrypt para obter e renovar os certificados de forma 100% automatizada.
- **Redirecionamento HTTP para HTTPS**: Configura regras globais para forçar conexões seguras automaticamente.
- **Suporte Multi-App (Compartilhamento de SSL entre aplicações)**:
  - **No Kamal 1 (Traefik)**: O Traefik roda de forma centralizada. A primeira aplicação configurada inicia o Traefik com a escuta e volume Let's Encrypt. Todas as demais aplicações compartilhando o mesmo servidor precisam apenas de `labels` apontando para o entrypoint `websecure` e o certresolver do Traefik, sem necessidade de redefinir o bloco global. O script também cria automaticamente o hook `.kamal/hooks/docker-setup` para garantir as permissões estritas de segurança (`chmod 600`) na persistência do arquivo `acme.json` no servidor remoto.
  - **No Kamal 2 (Kamal Proxy)**: O Kamal Proxy foi projetado para suportar múltiplas aplicações nativamente. Cada aplicação declara seu domínio e a diretiva `ssl: true` em seu bloco `proxy`. O Kamal Proxy centraliza as requisições das portas 80/443 e gerencia os certificados de cada aplicação dinamicamente de forma isolada e segura.

## Instalação Completa All-in-One (AIO)
A ferramenta permite a instalação coordenada e limpa de todos os recursos de uma só vez:

```bash
sudo python3 pg_main.py --all
```
Ou escolhendo a opção `6` no menu principal.

A instalação All-in-One realiza:
1. Instalação e configuração completa do Docker CE sem forçar um reboot imediato.
2. Instalação e configuração do Ruby, pacotes de compilação essenciais e Kamal.
3. Instalação e configuração do container oficial do Portainer CE opensource.
4. Instalação do PostgreSQL completo pronto para produção com criação de usuário/banco e testes de conexão.
5. Sugestão amigável de reinicialização do sistema no fim de todo o fluxo.

## Requisitos
- Python 3.8+
- Ferramentas PostgreSQL instaladas localmente (`pg_dump`, `pg_restore`, `psql`) OU Docker CLI (para cenários com containers)
- Acesso ao Docker daemon (se usar containers)
- Conexão de rede aos servidores de banco (se remotos)

## Instalação em Servidor Limpo
Para instalar e usar a ferramenta `py-db-install` em um servidor limpo (recomendado Debian/Ubuntu):

1. Instale as dependências básicas (Python e git):

```bash
sudo apt update
sudo apt install -y python3 python3-pip git
```

2. Clone o repositório diretamente do GitHub:

```bash
git clone https://github.com/pedropagotto/py-db-install.git
cd py-db-install
```

*(Substitua a URL pelo endereço real do seu repositório. Alternativamente, baixe o ZIP via GitHub e extraia os arquivos.)*

3. Nenhuma instalação via pip é necessária — o projeto usa apenas a biblioteca padrão do Python (sem dependências externas, conforme `requirements.txt`).

4. Execute a ferramenta utilizando o Make (ou diretamente com Python):

```bash
make start
```

Ou de forma tradicional:

```bash
python3 pg_main.py
```

Ou invoque os scripts diretamente:

```bash
python3 pg_install.py --help
python3 pg_backup_restore.py --help
```

**Nota sobre distribuição**: Atualmente o uso é via clone ou download manual. No futuro, será possível instalar com `pip install git+https://github.com/...` após adicionar `pyproject.toml`.

## Estrutura do Projeto
```
py-db-install/
├── README.md              # Documentação unificada do projeto
├── Makefile               # Atalhos para comandos comuns (make start, make install-all, etc.)
├── requirements.txt       # Requisitos (vazio, pois o projeto usa apenas a biblioteca padrão)
├── config.example.json    # Exemplo de configuração para backup/restore
├── docker_install.py      # Instalador de Docker CE otimizado para Debian/Ubuntu
├── kamal_install.py       # Instalador de Ruby e Kamal
├── kamal_ssl_config.py    # Gerador de configurações e templates SSL para Kamal 1 e 2
├── portainer_install.py   # Instalador de Portainer CE opensource
├── pg_install.py          # Instalador completo do PostgreSQL para Debian/Ubuntu
├── pg_backup_restore.py   # Script de Backup e Restore (Docker ou Bare-Metal)
├── pg_main.py             # Entrypoint da ferramenta interativa e direta All-in-One
└── .env.example           # Exemplo de variáveis de ambiente para credenciais
```

## Como Usar

### 1. Configuração
Copie `config.example.json` para `config.json` e preencha os dados.

Ou use variáveis de ambiente / argumentos CLI.

### 2. Executar Backup
```bash
python pg_backup_restore.py backup --source-type docker --source-container meu_postgres --source-db minha_db --backup-file backup.sql
```

### 3. Executar Restore
```bash
python pg_backup_restore.py restore --target-type local --target-host localhost --target-db minha_db --backup-file backup.sql
```

### Exemplos de Cenários

**Cenário 1: Docker → Local file → Servidor bare-metal**
```bash
# Backup
python pg_backup_restore.py backup --source-type docker --source-container pg_source --source-db appdb --backup-file /tmp/backup.dump --format custom

# Restore
python pg_backup_restore.py restore --target-type local --target-host 192.168.1.100 --target-port 5432 --target-db appdb --target-user postgres --backup-file /tmp/backup.dump --format custom
```

**Cenário 2: Docker → Docker**
```bash
python pg_backup_restore.py backup-restore \
  --source-type docker --source-container pg_a --source-db db1 \
  --target-type docker --target-container pg_b --target-db db2
```

**Cenário 3: Servidor → Servidor (bare-metal)**
```bash
python pg_backup_restore.py backup-restore \
  --source-type local --source-host db1.example.com --source-db production \
  --target-type local --target-host db2.example.com --target-db staging
```

## Segurança
- Nunca armazene senhas em texto plano. Use variáveis de ambiente (`PGPASSWORD`) ou `.pgpass`.
- O script suporta passagem de senha via variável de ambiente.

## Desenvolvimento
O projeto usa apenas a biblioteca padrão do Python para máxima portabilidade.

## Licença
MIT
