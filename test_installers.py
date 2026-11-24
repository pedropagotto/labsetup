import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import subprocess
from pathlib import Path

# Adiciona o diretório do projeto ao sys.path para podermos importar os módulos
sys.path.insert(0, str(Path(__file__).parent))

import portainer_install
import pg_main
import kamal_ssl_config
import pg_backup_restore
import mssql_backup_restore
import mssql_install
import mssql_to_pg_ddl


class TestPgBackupRestore(unittest.TestCase):

    @patch("getpass.getpass", return_value="secretpass")
    @patch("builtins.input")
    def test_prompt_connection_details(self, mock_input, mock_getpass):
        # Simula as entradas do usuário: host, port, db, user, ssl_choice
        mock_input.side_effect = ["aurora.aws.com", "5432", "mydb", "myuser", "1"]
        
        conn = pg_backup_restore.prompt_connection_details("source")
        
        self.assertEqual(conn["type"], "local")
        self.assertEqual(conn["host"], "aurora.aws.com")
        self.assertEqual(conn["port"], 5432)
        self.assertEqual(conn["database"], "mydb")
        self.assertEqual(conn["user"], "myuser")
        self.assertEqual(conn["password"], "secretpass")
        self.assertEqual(conn["sslmode"], "require")

    @patch("pg_backup_restore.run_pg_tool")
    def test_do_backup_local_type_valid(self, mock_run_pg_tool):
        args = MagicMock()
        args.source = {
            "type": "local",
            "host": "aurora.aws.com",
            "port": 5432,
            "database": "mydb",
            "user": "myuser",
            "password": "secretpass",
            "sslmode": "require"
        }
        args.backup_file = "/tmp/test.dump"
        args.format = "custom"

        pg_backup_restore.do_backup(args)

        mock_run_pg_tool.assert_called_once_with(
            "pg_dump",
            ["-U", "myuser", "-h", "aurora.aws.com", "-p", "5432", "-d", "mydb", "-F", "c", "-b", "-v"],
            "secretpass",
            sslmode="require",
            output_file="/tmp/test.dump"
        )

    @patch("pg_backup_restore.save_credentials_file")
    @patch("pg_backup_restore.ensure_roles_exist_on_target", return_value={"readonly_user": "randompass123"})
    @patch("pg_backup_restore.extract_roles_from_dump", return_value={"readonly_user"})
    @patch("pg_backup_restore.run_pg_tool")
    def test_do_restore_local_type_valid(self, mock_run_pg_tool, mock_extract, mock_ensure, mock_save):
        args = MagicMock()
        args.target = {
            "type": "local",
            "host": "vps.hostinger.com",
            "port": 5432,
            "database": "mydb",
            "user": "myuser",
            "password": "secretpass",
            "sslmode": "prefer"
        }
        args.backup_file = "/tmp/test.dump"
        args.format = "custom"

        pg_backup_restore.do_restore(args)

        mock_extract.assert_called_once_with("/tmp/test.dump", "custom")
        mock_ensure.assert_called_once_with(args.target, {"readonly_user"})
        mock_run_pg_tool.assert_called_once_with(
            "pg_restore",
            ["-U", "myuser", "-h", "vps.hostinger.com", "-p", "5432", "-d", "mydb", "-v", "--clean", "--if-exists", "--no-owner"],
            "secretpass",
            sslmode="prefer",
            input_file="/tmp/test.dump"
        )
        mock_save.assert_called_once_with(args.target, {"readonly_user": "randompass123"})

    @patch("pg_backup_restore.run_pg_tool")
    @patch("getpass.getpass", return_value="adminpass")
    @patch("builtins.input")
    def test_create_pg_user_readonly(self, mock_input, mock_getpass, mock_run_pg_tool):
        # Simula as respostas do usuário: host, port, admin_user, ssl_choice, target_db, new_username, role_choice
        mock_input.side_effect = [
            "localhost", "5432", "postgres", "3", "meu_banco", "leitor_app", "2"
        ]

        success = pg_backup_restore.create_pg_user()
        self.assertTrue(success)

        # Verifica se o psql foi chamado 2 vezes (1 para criar a role e 1 para atribuir GRANTs)
        self.assertEqual(mock_run_pg_tool.call_count, 2)

    @patch("pg_backup_restore.run_pg_tool")
    @patch("getpass.getpass", return_value="adminpass")
    @patch("builtins.input")
    def test_reset_pg_user_password(self, mock_input, mock_getpass, mock_run_pg_tool):
        # Simula as respostas do usuário: host, port, admin_user, ssl_choice, target_user, opt_pwd
        mock_input.side_effect = [
            "localhost", "5432", "postgres", "3", "usuario_teste", "1"
        ]

        success = pg_backup_restore.reset_pg_user_password()
        self.assertTrue(success)

        # Verifica se o psql foi chamado 1 vez para redefinir a senha
        mock_run_pg_tool.assert_called_once()

    def test_generate_kamal1_config(self):
        content = kamal_ssl_config.generate_kamal1_config(
            service_name="test-app",
            domain="app.test.com",
            email="admin@test.com",
            container_port=3000,
            registry_user="myuser"
        )
        self.assertIn("service: test-app", content)
        self.assertIn("Host(`app.test.com`)", content)
        self.assertIn("certificatesResolvers.letsencrypt.acme.email: \"admin@test.com\"", content)
        self.assertIn("traefik.http.services.test-app-web.loadbalancer.server.port: 3000", content)
        self.assertIn("myuser/test-app", content)

    def test_generate_kamal2_config(self):
        content = kamal_ssl_config.generate_kamal2_config(
            service_name="test-app-v2",
            domain="app2.test.com",
            container_port=80,
            registry_user="myuser"
        )
        self.assertIn("service: test-app-v2", content)
        self.assertIn("ssl: true", content)
        self.assertIn("host: app2.test.com", content)
        self.assertIn("app_port: 80", content)
        self.assertIn("myuser/test-app-v2", content)

    def test_generate_kamal1_hook_script(self):
        content = kamal_ssl_config.generate_kamal1_hook_script()
        self.assertIn("mkdir -p /letsencrypt", content)
        self.assertIn("chmod 600 /letsencrypt/acme.json", content)

    @patch("kamal_ssl_config.Path.mkdir")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("kamal_ssl_config.os.chmod")
    def test_setup_ssl_config_kamal1(self, mock_chmod, mock_open, mock_mkdir):
        success = kamal_ssl_config.setup_ssl_config(
            version=1,
            service_name="app",
            domain="example.com",
            email="admin@example.com",
            container_port=3000,
            registry_user="user",
            output_dir="/fake/dir"
        )
        self.assertTrue(success)
        mock_mkdir.assert_called()
        self.assertEqual(mock_open.call_count, 2)  # Config file and hook file
        mock_chmod.assert_called_once()

    @patch("kamal_ssl_config.Path.mkdir")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_setup_ssl_config_kamal2(self, mock_open, mock_mkdir):
        success = kamal_ssl_config.setup_ssl_config(
            version=2,
            service_name="app",
            domain="example.com",
            email=None,
            container_port=80,
            registry_user="user",
            output_dir="/fake/dir"
        )
        self.assertTrue(success)
        mock_mkdir.assert_called()
        mock_open.assert_called_once()


class TestPortainerInstall(unittest.TestCase):

    @patch('subprocess.run')
    def test_is_docker_installed_true(self, mock_run):
        # Simula que docker --version funciona
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(portainer_install.is_docker_installed())
        mock_run.assert_called_with(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    @patch('subprocess.run')
    def test_is_docker_installed_false(self, mock_run):
        # Simula erro ao rodar docker --version (FileNotFoundError)
        mock_run.side_effect = FileNotFoundError()
        self.assertFalse(portainer_install.is_docker_installed())

    @patch('subprocess.run')
    def test_is_docker_running_true(self, mock_run):
        # Simula que docker info funciona
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(portainer_install.is_docker_running())

    @patch('subprocess.run')
    def test_is_docker_running_false(self, mock_run):
        import subprocess as sp
        # Simula erro ao rodar docker info (CalledProcessError)
        mock_run.side_effect = sp.CalledProcessError(1, ["docker", "info"])
        self.assertFalse(portainer_install.is_docker_running())

    def test_install_portainer_skip_install(self):
        # Quando --skip-install é passado, deve retornar True sem fazer verificações do docker
        self.assertTrue(portainer_install.install_portainer(skip_install=True))

    @patch('portainer_install.is_docker_installed')
    def test_install_portainer_no_docker(self, mock_installed):
        # Caso em que docker não está instalado
        mock_installed.return_value = False
        self.assertFalse(portainer_install.install_portainer(skip_install=False))

    @patch('portainer_install.is_docker_installed')
    @patch('portainer_install.is_docker_running')
    def test_install_portainer_docker_not_running(self, mock_running, mock_installed):
        # Caso em que docker está instalado mas não está rodando
        mock_installed.return_value = True
        mock_running.return_value = False
        self.assertFalse(portainer_install.install_portainer(skip_install=False))

    @patch('portainer_install.is_docker_installed')
    @patch('portainer_install.is_docker_running')
    @patch('subprocess.run')
    @patch('portainer_install.run_cmd')
    def test_install_portainer_successful_new(self, mock_run_cmd, mock_sub_run, mock_running, mock_installed):
        # Caso feliz: instalação limpa (sem container existente)
        mock_installed.return_value = True
        mock_running.return_value = True
        
        # Simula que docker ps não encontra nenhum container chamado portainer
        mock_sub_run.return_value = MagicMock(stdout="", returncode=0)
        
        self.assertTrue(portainer_install.install_portainer(skip_install=False))
        
        # Verifica se o volume e o container foram criados
        mock_run_cmd.assert_any_call(["docker", "volume", "create", "portainer_data"])
        mock_run_cmd.assert_any_call([
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

    @patch('portainer_install.is_docker_installed')
    @patch('portainer_install.is_docker_running')
    @patch('subprocess.run')
    @patch('portainer_install.run_cmd')
    def test_install_portainer_container_exists(self, mock_run_cmd, mock_sub_run, mock_running, mock_installed):
        # Caso em que o container portainer já existe: deve parar e remover
        mock_installed.return_value = True
        mock_running.return_value = True
        
        # Simula que docker ps encontra um container com nome portainer
        mock_sub_run.return_value = MagicMock(stdout="portainer\n", returncode=0)
        
        self.assertTrue(portainer_install.install_portainer(skip_install=False))
        
        # Verifica se tentou parar e remover o container antigo antes do run
        mock_run_cmd.assert_any_call(["docker", "stop", "portainer"], check=False)
        mock_run_cmd.assert_any_call(["docker", "rm", "portainer"], check=False)


class TestPgMainIntegration(unittest.TestCase):

    def test_filter_args_portainer(self):
        # Testa se os argumentos do portainer são filtrados corretamente
        args = ["--portainer", "--install-portainer", "--some-other-arg"]
        filtered = pg_main.filter_args(args)
        self.assertEqual(filtered, ["--some-other-arg"])

    def test_filter_args_kamal_ssl(self):
        # Testa se os argumentos do kamal ssl são filtrados corretamente
        args = ["--kamal-ssl", "--config-kamal-ssl", "--some-other-arg"]
        filtered = pg_main.filter_args(args)
        self.assertEqual(filtered, ["--some-other-arg"])

    def test_filter_args_mssql(self):
        args = ["--mssql", "--install-mssql", "--mssql-backup-restore", "--mssql-to-pg-ddl", "--mssql-reset-passwords", "--some-other-arg"]
        filtered = pg_main.filter_args(args)
        self.assertEqual(filtered, ["--some-other-arg"])


class TestMssqlBackupRestore(unittest.TestCase):

    def test_is_azure_sql_host(self):
        self.assertTrue(mssql_backup_restore.is_azure_sql_host("myserver.database.windows.net"))
        self.assertFalse(mssql_backup_restore.is_azure_sql_host("localhost"))

    def test_generate_random_password_complexity(self):
        pwd = mssql_backup_restore.generate_random_password(16)
        self.assertEqual(len(pwd), 16)
        self.assertTrue(any(c.isupper() for c in pwd))
        self.assertTrue(any(c.islower() for c in pwd))
        self.assertTrue(any(c.isdigit() for c in pwd))
        self.assertTrue(any(c in "!@#$%^&*" for c in pwd))

    @patch("getpass.getpass", return_value="AzurePass123!")
    @patch("builtins.input")
    def test_prompt_connection_details_azure(self, mock_input, mock_getpass):
        mock_input.side_effect = ["myserver.database.windows.net", "1433", "appdb", "sqladmin", "1"]
        conn = mssql_backup_restore.prompt_connection_details("source")
        self.assertTrue(conn["is_azure"])
        self.assertEqual(conn["port"], 1433)
        self.assertEqual(conn["ssl_mode"], "require")
        self.assertEqual(conn["database"], "appdb")

    @patch("mssql_backup_restore.run_sqlpackage")
    def test_do_backup_bacpac(self, mock_run_sqlpackage):
        args = MagicMock()
        args.source = {
            "type": "local",
            "is_azure": True,
            "host": "myserver.database.windows.net",
            "port": 1433,
            "database": "appdb",
            "user": "sqladmin",
            "password": "secret",
            "ssl_mode": "require",
        }
        args.backup_file = "/tmp/test_mssql.bacpac"
        args.format = "bacpac"

        mssql_backup_restore.do_backup(args)
        mock_run_sqlpackage.assert_called_once()
        call_args = mock_run_sqlpackage.call_args[0][0]
        self.assertEqual(call_args[0], "/Action:Export")
        self.assertIn("Encrypt=True", call_args[1])
        self.assertIn("TrustServerCertificate=False", call_args[1])

    @patch("mssql_backup_restore.run_sqlpackage")
    def test_do_restore_bacpac(self, mock_run_sqlpackage):
        args = MagicMock()
        args.target = {
            "type": "local",
            "is_azure": False,
            "host": "localhost",
            "port": 1433,
            "database": "appdb",
            "user": "sa",
            "password": "secret",
            "ssl_mode": "trust",
        }
        args.backup_file = "/tmp/test_mssql.bacpac"
        args.format = "bacpac"

        mssql_backup_restore.do_restore(args)
        mock_run_sqlpackage.assert_called_once()
        call_args = mock_run_sqlpackage.call_args[0][0]
        self.assertEqual(call_args[0], "/Action:Import")
        self.assertIn("TrustServerCertificate=True", call_args[1])

    def test_do_backup_bak_rejects_azure(self):
        args = MagicMock()
        args.source = {
            "type": "local",
            "is_azure": True,
            "host": "myserver.database.windows.net",
            "port": 1433,
            "database": "appdb",
            "user": "sqladmin",
            "password": "secret",
            "ssl_mode": "require",
        }
        args.backup_file = "/tmp/test.bak"
        args.format = "bak"

        with self.assertRaises(ValueError):
            mssql_backup_restore.do_backup(args)

    @patch("mssql_backup_restore.run_sqlcmd")
    @patch("getpass.getpass", return_value="AdminPass123!")
    @patch("builtins.input")
    def test_create_mssql_user_azure_contained(self, mock_input, mock_getpass, mock_run_sqlcmd):
        mock_input.side_effect = [
            "myserver.database.windows.net", "1433", "sqladmin", "1", "appdb", "reader_app", "2"
        ]
        success = mssql_backup_restore.create_mssql_user()
        self.assertTrue(success)
        self.assertEqual(mock_run_sqlcmd.call_count, 2)

    @patch("mssql_backup_restore.run_sqlcmd")
    @patch("getpass.getpass", return_value="AdminPass123!")
    @patch("builtins.input")
    def test_create_mssql_user_sqlserver_login(self, mock_input, mock_getpass, mock_run_sqlcmd):
        mock_input.side_effect = [
            "localhost", "1433", "1", "sa", "2", "appdb", "writer_app", "3"
        ]
        success = mssql_backup_restore.create_mssql_user()
        self.assertTrue(success)
        # 1: CREATE LOGIN (master), 2: CREATE USER (appdb), 3: ALTER ROLE (appdb)
        self.assertEqual(mock_run_sqlcmd.call_count, 3)

    @patch("mssql_backup_restore.run_sqlcmd")
    @patch("getpass.getpass", return_value="AdminPass123!")
    @patch("builtins.input")
    def test_reset_mssql_user_password_sqlserver(self, mock_input, mock_getpass, mock_run_sqlcmd):
        mock_input.side_effect = [
            "localhost", "1433", "1", "sa", "2", "app_user", "1"
        ]
        success = mssql_backup_restore.reset_mssql_user_password()
        self.assertTrue(success)
        mock_run_sqlcmd.assert_called_once()


class TestMssqlInstall(unittest.TestCase):

    @patch("shutil.which", return_value="/usr/bin/docker")
    @patch("mssql_install.configure_firewall")
    @patch("mssql_install.time.sleep")
    @patch("mssql_install.run_cmd")
    @patch("subprocess.run")
    def test_install_mssql_docker(self, mock_sub_run, mock_run_cmd, mock_sleep, mock_fw, mock_which):
        mssql_install.install_mssql_docker("StrongPass123!", container_name="mssql_test")
        mock_run_cmd.assert_any_call(["docker", "volume", "create", "mssql_data"])
        mock_fw.assert_called_once()

    @patch("os.geteuid", return_value=1000)
    def test_reset_sa_password_requires_root(self, mock_euid):
        self.assertFalse(mssql_install.reset_sa_password_local("StrongPass123!"))


class TestMssqlToPgDdl(unittest.TestCase):

    def test_type_mapping(self):
        self.assertEqual(mssql_to_pg_ddl.map_tsql_type("uniqueidentifier"), ("UUID", None))
        self.assertEqual(mssql_to_pg_ddl.map_tsql_type("bit"), ("BOOLEAN", None))
        self.assertEqual(mssql_to_pg_ddl.map_tsql_type("nvarchar", max_length=-1), ("TEXT", None))
        self.assertEqual(mssql_to_pg_ddl.map_tsql_type("nvarchar", max_length=120), ("VARCHAR(120)", None))
        self.assertEqual(mssql_to_pg_ddl.map_tsql_type("datetimeoffset"), ("TIMESTAMPTZ", None))
        self.assertEqual(mssql_to_pg_ddl.map_tsql_type("money"), ("NUMERIC(19,4)", None))
        pg_type, warn = mssql_to_pg_ddl.map_tsql_type("geography")
        self.assertEqual(pg_type, "TEXT")
        self.assertIsNotNone(warn)

    def test_default_mapping(self):
        self.assertEqual(mssql_to_pg_ddl.map_default_expr("(newid())", "UUID")[0], "gen_random_uuid()")
        self.assertEqual(mssql_to_pg_ddl.map_default_expr("(getdate())", "TIMESTAMP")[0], "CURRENT_TIMESTAMP")
        self.assertEqual(mssql_to_pg_ddl.map_default_expr("((1))", "BOOLEAN")[0], "true")

    def test_naming_strategies(self):
        self.assertEqual(mssql_to_pg_ddl.format_identifier("[UserAccounts]", "lowercase"), "useraccounts")
        self.assertEqual(mssql_to_pg_ddl.format_identifier("[UserAccounts]", "snake_case"), "user_accounts")
        self.assertEqual(mssql_to_pg_ddl.format_identifier("[UserAccounts]", "preserve"), '"UserAccounts"')

    def test_extract_sql_and_generate_ddl(self):
        tsql = """
        CREATE SCHEMA [app];
        GO
        CREATE TABLE [app].[Users] (
            [Id] INT IDENTITY(1,1) NOT NULL,
            [ExternalId] UNIQUEIDENTIFIER DEFAULT (NEWID()) NOT NULL,
            [Email] NVARCHAR(255) NOT NULL,
            [IsActive] BIT DEFAULT ((1)) NOT NULL,
            [CreatedAt] DATETIMEOFFSET DEFAULT (SYSDATETIMEOFFSET()) NOT NULL,
            CONSTRAINT [PK_Users] PRIMARY KEY ([Id])
        );
        GO
        CREATE TABLE [app].[Orders] (
            [Id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
            [UserId] INT NOT NULL,
            CONSTRAINT [FK_Orders_Users] FOREIGN KEY ([UserId]) REFERENCES [app].[Users]([Id]) ON DELETE CASCADE
        );
        GO
        CREATE UNIQUE INDEX [IX_Users_Email] ON [app].[Users] ([Email]);
        GO
        CREATE VIEW [app].[ActiveUsers] AS SELECT * FROM [app].[Users];
        """
        schema = mssql_to_pg_ddl.extract_schema_from_sql(tsql)
        ddl, warnings = mssql_to_pg_ddl.generate_pg_ddl(schema, naming="snake_case")

        self.assertIn("CREATE SCHEMA IF NOT EXISTS app;", ddl)
        self.assertIn("id INTEGER GENERATED BY DEFAULT AS IDENTITY NOT NULL", ddl)
        self.assertIn("external_id UUID DEFAULT gen_random_uuid() NOT NULL", ddl)
        self.assertIn("is_active BOOLEAN DEFAULT true NOT NULL", ddl)
        self.assertIn("ALTER TABLE app.orders ADD CONSTRAINT fk_orders_users FOREIGN KEY (user_id) REFERENCES app.users (id) ON DELETE CASCADE;", ddl)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON app.users (email);", ddl)
        self.assertTrue(any("VIEW 'app.ActiveUsers'" in w for w in warnings))

    def test_extract_from_bacpac_zip(self):
        import tempfile
        import zipfile

        tsql = "CREATE TABLE [dbo].[Items] ([Id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY, [Name] NVARCHAR(50) NOT NULL);"
        with tempfile.NamedTemporaryFile(suffix=".bacpac", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with zipfile.ZipFile(tmp_path, "w") as zf:
                zf.writestr("model.sql", tsql)
            schema = mssql_to_pg_ddl.extract_schema_from_file(tmp_path)
            ddl, _ = mssql_to_pg_ddl.generate_pg_ddl(schema, naming="lowercase")
            self.assertIn("CREATE TABLE IF NOT EXISTS public.items", ddl)
            self.assertIn("name VARCHAR(50) NOT NULL", ddl)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


if __name__ == "__main__":
    import subprocess
    unittest.main()
