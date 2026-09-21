import ast
import configparser
import contextlib
import io
import re
import runpy
import socketserver
import unittest
from pathlib import Path
from unittest import mock

from app_paths import APPLICATION_DIRECTORY, CONFIG_FILE
from cgi_utils import QueryForm


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(ROOT.glob("*.py"))


def ast_module(body):
    kwargs = {"body": body}
    if "type_ignores" in ast.Module._fields:
        kwargs["type_ignores"] = []
    return ast.Module(**kwargs)


class Python3CompatibilityTests(unittest.TestCase):
    @staticmethod
    def config_template(filename):
        source = (ROOT / filename).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filename)
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(target, ast.Name) and target.id == "config_lines" for target in node.targets):
                return ast.literal_eval(node.value)
        raise AssertionError("config_lines not found in %s" % filename)

    def test_all_scripts_compile_as_python3(self):
        for path in SCRIPTS:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                compile(source, str(path), "exec")

    def test_all_scripts_use_python3_shebang(self):
        for path in SCRIPTS:
            with self.subTest(path=path.name):
                first_line = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(first_line, "#!/usr/bin/python3")

    def test_legacy_python2_names_are_absent(self):
        legacy_names = {"ConfigParser", "SocketServer", "xrange"}
        removed_modules = {"cgi", "cgitb"}
        for path in SCRIPTS:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
                imported_names = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names
                }
                referenced_names = {
                    node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
                }
                self.assertFalse(legacy_names & (imported_names | referenced_names))
                self.assertFalse(removed_modules & imported_names)

    def test_pigpio_dependency_is_absent(self):
        for path in SCRIPTS:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imported_names = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names
                }
                self.assertNotIn("pigpio", imported_names)

    def test_config_path_defaults_to_application_directory(self):
        self.assertEqual(Path(APPLICATION_DIRECTORY), ROOT)
        self.assertEqual(Path(CONFIG_FILE), ROOT / "sprinkler.config")
        for path in SCRIPTS:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("/var/www/html/cgi-bin", source)

    def test_query_form_parses_get_parameters(self):
        form = QueryForm({"QUERY_STRING": "submit=Start&duration=72&blank="})
        self.assertEqual(form.getfirst("submit"), "Start")
        self.assertEqual(form.getvalue("duration"), "72")
        self.assertEqual(form.getfirst("blank"), "")
        self.assertEqual(form.getfirst("missing", "fallback"), "fallback")

    def test_default_config_templates_do_not_embed_api_keys(self):
        key_with_value = re.compile(r"^apikey[ \t]*=[ \t]*\S+", re.MULTILINE)
        for filename in ("index.py", "settings.py"):
            with self.subTest(path=filename):
                source = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIsNone(key_with_value.search(source))

    def test_default_config_templates_are_valid_and_identical(self):
        index_template = self.config_template("index.py")
        settings_template = self.config_template("settings.py")
        self.assertEqual(index_template, settings_template)

        config = configparser.ConfigParser()
        config.read_string(index_template)
        self.assertEqual(config.get("forecastio", "apikey"), "")
        self.assertEqual(config.get("forecastio", "lat"), "")
        self.assertEqual(config.get("forecastio", "lng"), "")
        self.assertEqual(len(config.get("Station GPIOs", "pins").split(",")), 8)

        example = configparser.ConfigParser()
        example.read(str(ROOT / "sprinkler.config.example"), encoding="utf-8")
        self.assertEqual(config.sections(), example.sections())
        for section in config.sections():
            self.assertEqual(dict(config.items(section)), dict(example.items(section)))

    def test_socket_writes_explicitly_encode_text(self):
        for path in SCRIPTS:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                writes = [
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"send", "sendall"}
                ]
                for call in writes:
                    self.assertTrue(call.args)
                    argument = call.args[0]
                    self.assertIsInstance(argument, ast.Call)
                    self.assertIsInstance(argument.func, ast.Attribute)
                    self.assertEqual(argument.func.attr, "encode")

    def test_scheduler_status_responses_are_bytes(self):
        source = (ROOT / "sprinkler.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="sprinkler.py")
        handler_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ThreadedServer"
        )
        namespace = {
            "socketserver": socketserver,
            "running": False,
            "enabled": True,
            "delay": False,
            "futuretime": 123.0,
            "lastrun": "never",
            "test": False,
            "test_time": 0,
        }
        exec(compile(ast_module([handler_node]), "sprinkler.py", "exec"), namespace)

        class FakeRequest:
            def __init__(self):
                self.received = [b"status:0", b""]
                self.sent = []

            def recv(self, _size):
                return self.received.pop(0)

            def sendall(self, data):
                self.sent.append(data)

            def close(self):
                pass

        request = FakeRequest()
        with contextlib.redirect_stdout(io.StringIO()):
            namespace["ThreadedServer"](request, ("local", 0), object())
        self.assertEqual(request.sent, [b"Stopped. Last run never"])

    def test_scheduler_reports_and_controls_station_relays(self):
        source = (ROOT / "sprinkler.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="sprinkler.py")
        handler_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ThreadedServer"
        )

        class FakeRelays:
            def __init__(self):
                self.states = {5: False, 6: False}

            def is_on(self, pin):
                return self.states[pin]

            def on(self, pin):
                self.states[pin] = True

            def off(self, pin):
                self.states[pin] = False

            def all_off(self):
                for pin in self.states:
                    self.states[pin] = False

        relays = FakeRelays()
        namespace = {
            "socketserver": socketserver,
            "station": [5, 6],
            "relays": relays,
            "running": False,
            "enabled": True,
            "delay": False,
            "futuretime": 123.0,
            "lastrun": "never",
            "test": False,
            "test_time": 0,
        }
        exec(compile(ast_module([handler_node]), "sprinkler.py", "exec"), namespace)

        class FakeRequest:
            def __init__(self, command):
                self.received = [command.encode("utf-8"), b""]
                self.sent = []

            def recv(self, _size):
                return self.received.pop(0)

            def sendall(self, data):
                self.sent.append(data)

            def close(self):
                pass

        def request(command):
            fake_request = FakeRequest(command)
            with contextlib.redirect_stdout(io.StringIO()):
                namespace["ThreadedServer"](
                    fake_request, ("local", 0), object()
                )
            return fake_request.sent

        self.assertEqual(request("station_status:0"), [b"5=off,6=off"])
        self.assertEqual(request("station_on:5"), [b"ok"])
        self.assertTrue(relays.states[5])
        self.assertEqual(request("station_status:0"), [b"5=on,6=off"])
        self.assertEqual(request("station_on:6"), [b"ok"])
        self.assertFalse(relays.states[5])
        self.assertTrue(relays.states[6])
        self.assertEqual(request("station_off:6"), [b"ok"])
        self.assertFalse(relays.states[6])
        self.assertEqual(request("station_on:5"), [b"ok"])
        self.assertEqual(request("station_off:5"), [b"ok"])
        self.assertFalse(relays.states[5])
        self.assertEqual(request("station_on:99"), [b"error"])

    def test_systemd_service_uses_python3_and_gpio_group(self):
        service = (ROOT / "systemd" / "pi-sprinkler-legacy.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("ExecStart=/usr/bin/python3", service)
        self.assertIn("RuntimeDirectory=pi-sprinkler", service)
        self.assertIn("RuntimeDirectoryMode=0750", service)
        self.assertIn("WorkingDirectory=/run/pi-sprinkler", service)
        self.assertNotIn("WorkingDirectory=/usr/lib/cgi-bin", service)
        self.assertIn("/usr/lib/cgi-bin/sprinkler.config", service)
        self.assertIn("SupplementaryGroups=gpio", service)
        self.assertIn("Restart=on-failure", service)
        self.assertNotIn("pigpiod", service)

        scheduler = (ROOT / "sprinkler.py").read_text(encoding="utf-8")
        self.assertIn("ThreadedTCPServer(('127.0.0.1', 5555)", scheduler)

    def test_readme_preserves_relay_and_sudo_safety(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("valve transformer disconnected", readme)
        self.assertIn("sudo apt install -y git ca-certificates", readme)
        self.assertIn("can take about 15 minutes", readme)
        service = (ROOT / "systemd" / "pi-sprinkler.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("RuntimeDirectory", service)
        self.assertNotIn("NOPASSWD:/sbin/shutdown", readme)

    def test_index_renders_without_weather_configuration(self):
        template = self.config_template("index.py")

        def read_config(parser, _filename, encoding=None):
            parser.read_string(template)
            return [_filename]

        class FakeSocket:
            def connect(self, _address):
                pass

            def sendall(self, _data):
                pass

            def recv(self, _size):
                return b"Stopped. Last run never"

            def close(self):
                pass

        output = io.StringIO()
        with mock.patch.object(configparser.ConfigParser, "read", read_config):
            with mock.patch("socket.socket", return_value=FakeSocket()):
                with mock.patch("urllib.request.urlopen") as urlopen:
                    with contextlib.redirect_stdout(output):
                        runpy.run_path(str(ROOT / "index.py"), run_name="__main__")

        urlopen.assert_not_called()
        self.assertIn("Weather is not configured", output.getvalue())


if __name__ == "__main__":
    unittest.main()
