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

from cgi_utils import QueryForm


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(ROOT.glob("*.py"))


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
        exec(compile(ast.Module(body=[handler_node]), "sprinkler.py", "exec"), namespace)

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
