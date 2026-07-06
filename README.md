# Database PG - Backup e Restore para PostgreSQL

Projeto simples em Python para facilitar backups e restores de bancos de dados PostgreSQL, suportando cenários com Docker e servidores bare-metal.

## Objetivo
- Portátil: pode ser copiado e executado em qualquer máquina com Python 3.
- Suporta 3 cenários principais:
  1. Backup de container Docker → arquivo local → Restore em servidor PostgreSQL sem container.
  2. Backup de container Docker → Restore direto em outro container Docker.
  3. Backup de servidor PostgreSQL sem container → Restore em outro servidor sem container.

## Ferramenta Principal (pg_main.py)
O script `pg_main.py` é o entrypoint principal que permite escolher interativamente qual operação executar:

```bash
python pg_main.py
```

Opções disponíveis no menu:
- `1` → Executa `pg_backup_restore.py` (backup, restore ou backup-restore)
- `2` → Executa `pg_install.py` (instalação do PostgreSQL)
- `0` → Sai da ferramenta

Você também pode passar argumentos extras: `python pg_main.py --help` (serão repassados ao script escolhido).

## Instalação do PostgreSQL (Debian/Ubuntu)
O script `pg_install.py` automatiza a instalação completa do PostgreSQL em servidores Debian ou Ubuntu:

```bash
sudo python pg_install.py
```

Opções:
- `--user NOME` : nome do usuário (padrão: postgres_app)
- `--database NOME` : nome do banco (padrão: app_db)
- `--password SENHA` : senha customizada (será solicitada interativamente se omitida; gerada aleatória se deixada vazia)
- `--skip-install` : pula instalação (útil para configurar apenas usuário/banco)

Ao final, o script:
- Imprime as credenciais (usuário, senha, host, porta, banco)
- Realiza teste de conexão com `SELECT 1` para confirmar que está funcionando

**Nota**: Execute sempre com `sudo`. A senha gerada é exibida apenas uma vez.

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

4. Execute a ferramenta:

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
├── README.md
├── requirements.txt
├── config.example.json
├── pg_backup_restore.py
├── pg_install.py
├── pg_main.py
└── .env.example
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
