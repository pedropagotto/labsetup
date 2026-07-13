import unittest
from unittest.mock import patch, MagicMock
import sys
import os
from pathlib import Path

# Adiciona o diretório do projeto ao sys.path para podermos importar os módulos
sys.path.insert(0, str(Path(__file__).parent))

import portainer_install
import pg_main
import kamal_ssl_config


class TestKamalSSLConfig(unittest.TestCase):

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


if __name__ == "__main__":
    import subprocess
    unittest.main()
