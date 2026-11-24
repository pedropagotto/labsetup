.DEFAULT_GOAL := start

.PHONY: start help install-postgres install-mssql install-docker install-kamal install-portainer config-kamal-ssl install-all backup-restore mssql-backup-restore mssql-to-pg-ddl test

start:
	python3 pg_main.py

help:
	@echo "DATABASE PG - Comandos disponíveis via Make"
	@echo "==========================================="
	@echo "make start             - Inicia o menu principal interativo (pg_main.py)"
	@echo "make install-postgres      - Executa o instalador do PostgreSQL"
	@echo "make install-mssql         - Executa o instalador do SQL Server"
	@echo "make install-docker        - Executa o instalador do Docker CE"
	@echo "make install-kamal         - Executa o instalador do Kamal"
	@echo "make install-portainer     - Executa o instalador do Portainer CE"
	@echo "make config-kamal-ssl      - Gera templates de configuração de SSL Let's Encrypt para o Kamal"
	@echo "make install-all           - Executa o instalador completo All-in-One (PostgreSQL + Docker + Kamal + Portainer)"
	@echo "make backup-restore        - Executa a ferramenta de Backup/Restore PostgreSQL"
	@echo "make mssql-backup-restore  - Executa a ferramenta de Backup/Restore SQL Server / Azure SQL"
	@echo "make mssql-to-pg-ddl       - Converte estruturas DDL (SQL Server / Azure SQL -> PostgreSQL)"
	@echo "make test                  - Executa os testes automatizados do projeto"

install-postgres:
	sudo python3 pg_main.py --postgres

install-mssql:
	sudo python3 pg_main.py --mssql

install-docker:
	sudo python3 pg_main.py --docker

install-kamal:
	sudo python3 pg_main.py --kamal

install-portainer:
	sudo python3 pg_main.py --portainer

config-kamal-ssl:
	python3 pg_main.py --kamal-ssl

install-all:
	sudo python3 pg_main.py --all

backup-restore:
	python3 pg_main.py --backup-restore

mssql-backup-restore:
	python3 pg_main.py --mssql-backup-restore

mssql-to-pg-ddl:
	python3 pg_main.py --mssql-to-pg-ddl

test:
	python3 test_installers.py
