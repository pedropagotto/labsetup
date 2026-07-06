# Database PG - Backup e Restore para PostgreSQL

Projeto simples em Python para facilitar backups e restores de bancos de dados PostgreSQL, suportando cenários com Docker e servidores bare-metal.

## Objetivo
- Portátil: pode ser copiado e executado em qualquer máquina com Python 3.
- Suporta 3 cenários principais:
  1. Backup de container Docker → arquivo local → Restore em servidor PostgreSQL sem container.
  2. Backup de container Docker → Restore direto em outro container Docker.
  3. Backup de servidor PostgreSQL sem container → Restore em outro servidor sem container.

## Instalação do PostgreSQL (Debian/Ubuntu)
O script `pg_install.py` automatiza a instalação completa do PostgreSQL em servidores Debian ou Ubuntu:

```bash
sudo python pg_install.py
```

Opções:
- `--user NOME` : nome do usuário (padrão: postgres_app)
- `--database NOME` : nome do banco (padrão: app_db)
- `--password SENHA` : senha customizada (será gerada aleatória se omitida)
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

## Estrutura do Projeto
```
database-pg/
├── README.md
├── requirements.txt
├── config.example.json
├── pg_backup_restore.py
├── pg_install.py
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
