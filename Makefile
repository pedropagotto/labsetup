.DEFAULT_GOAL := start

.PHONY: start help install-postgres install-docker install-kamal install-portainer config-kamal-ssl install-all backup-restore test

start:
	python3 pg_main.py

help:
	@echo "DATABASE PG - Comandos disponíveis via Make"
	@echo "==========================================="
	@echo "make start             - Inicia o menu principal interativo (pg_main.py)"
	@echo "make install-postgres  - Executa o instalador do PostgreSQL"
	@echo "make install-docker    - Executa o instalador do Docker CE"
	@echo "make install-kamal     - Executa o instalador do Kamal"
	@echo "make install-portainer - Executa o instalador do Portainer CE"
	@echo "make config-kamal-ssl  - Gera templates de configuração de SSL Let's Encrypt para o Kamal"
	@echo "make install-all       - Executa o instalador completo All-in-One (PostgreSQL + Docker + Kamal + Portainer)"
	@echo "make backup-restore    - Executa a ferramenta de Backup/Restore"
	@echo "make test              - Executa os testes automatizados do projeto"

install-postgres:
	sudo python3 pg_main.py --postgres

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

test:
	python3 test_installers.py
