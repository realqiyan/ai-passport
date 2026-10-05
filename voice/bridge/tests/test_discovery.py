import argparse
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from voice_bridge import discovery
from voice_bridge.cli import configure, open_session


class DiscoveryTests(unittest.TestCase):
    def test_local_udp_ignores_invalid_packets_and_deduplicates_replies(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            server.settimeout(1)
            port = server.getsockname()[1]
            errors = []

            def device():
                try:
                    packet, peer = server.recvfrom(256)
                    self.assertTrue(packet.startswith(discovery.REQUEST))
                    nonce = packet[len(discovery.REQUEST):]
                    server.sendto(discovery.RESPONSE + b"wrong nonce", peer)
                    for _ in range(2):
                        server.sendto(discovery.RESPONSE + nonce, peer)
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=device)
            worker.start()
            with patch.object(discovery, "PORT", port), patch.object(
                    discovery, "broadcast_addresses", return_value=["127.0.0.1"]):
                self.assertEqual(discovery.discover_host(timeout=0.1), "127.0.0.1")
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])

    def test_multiple_devices_never_select_one_arbitrarily(self):
        nonce = "a" * 32
        channel = Mock()
        channel.__enter__ = Mock(return_value=channel)
        channel.__exit__ = Mock(return_value=False)
        channel.recvfrom.side_effect = [
            (discovery.RESPONSE + nonce.encode(), ("192.0.2.1", discovery.PORT)),
            (discovery.RESPONSE + nonce.encode(), ("192.0.2.2", discovery.PORT)),
        ] + [socket.timeout()] * 10000
        with patch.object(discovery.secrets, "token_hex", return_value=nonce), patch.object(
                discovery.socket, "socket", return_value=channel):
            with self.assertRaisesRegex(RuntimeError, "Multiple Passports"):
                discovery.discover_host(timeout=0.01)

    def test_no_device_reports_firmware_and_manual_address(self):
        with patch.object(discovery, "broadcast_addresses", return_value=["127.0.0.1"]):
            with self.assertRaisesRegex(TimeoutError, "start.sh wifi <IP>"):
                discovery.discover_host(timeout=0.01)

    def test_macos_broadcasts_include_all_interfaces(self):
        output = Mock(stdout="inet 192.0.2.2 netmask 0xffffff00 broadcast 192.0.2.255\n"
                             "inet 198.51.100.2 netmask 0xffffff00 broadcast 198.51.100.255")
        with patch.object(discovery.sys, "platform", "darwin"), patch.object(
                discovery.subprocess, "run", return_value=output):
            self.assertEqual(discovery.broadcast_addresses(),
                             ["192.0.2.255", "198.51.100.255", "255.255.255.255"])


class DiscoverySessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.host_file = Path(temporary.name) / "host"
        self.args = argparse.Namespace(serial=None, host=None, discover=True,
                                       host_file=self.host_file, token_file=Path(temporary.name) / "token")
        self.args.token_file.write_text("a" * 64)

    def connect(self, found=None, failure=None):
        with patch("voice_bridge.cli.discover_host", return_value=found, side_effect=failure), patch(
                "voice_bridge.cli.TcpLink") as link, patch("voice_bridge.cli.Session") as session:
            result = open_session(self.args)
            session.return_value.request.assert_called_once_with("hello", token="a" * 64)
            return result, link.call_args.args[0]

    def test_new_address_replaces_stale_cache_after_authentication(self):
        self.host_file.write_text("192.0.2.1\n")
        _, address = self.connect(found="192.0.2.2")
        self.assertEqual(address, "192.0.2.2")
        self.assertEqual(self.host_file.read_text(), "192.0.2.2\n")

    def test_explicit_address_is_cached_only_after_authentication(self):
        self.args.discover = False
        self.args.host = '192.0.2.3'
        self.host_file.write_text('192.0.2.1\n')
        with patch("voice_bridge.cli.TcpLink") as link, patch("voice_bridge.cli.Session") as session:
            session.return_value.request.side_effect = PermissionError('bad token')
            with self.assertRaises(PermissionError):
                open_session(self.args)
            self.assertEqual(self.host_file.read_text(), '192.0.2.1\n')
            session.return_value.request.side_effect = None
            open_session(self.args)
            self.assertEqual(self.host_file.read_text(), '192.0.2.3\n')

    def test_old_firmware_can_use_saved_address(self):
        self.host_file.write_text("192.0.2.1\n")
        _, address = self.connect(failure=TimeoutError("no discovery"))
        self.assertEqual(address, "192.0.2.1")

    def test_multiple_devices_do_not_fall_back_to_cache(self):
        self.host_file.write_text("192.0.2.1\n")
        with self.assertRaisesRegex(RuntimeError, "Multiple"), patch("voice_bridge.cli.TcpLink") as link:
            self.connect(failure=RuntimeError("Multiple devices"))
        link.assert_not_called()

    def test_failed_authentication_preserves_cache_and_closes_connection(self):
        self.host_file.write_text("192.0.2.1\n")
        with patch("voice_bridge.cli.discover_host", return_value="192.0.2.2"), patch(
                "voice_bridge.cli.TcpLink") as link, patch("voice_bridge.cli.Session") as session:
            session.return_value.request.side_effect = PermissionError("bad token")
            with self.assertRaises(PermissionError):
                open_session(self.args)
            link.return_value.close.assert_called_once()
        self.assertEqual(self.host_file.read_text(), "192.0.2.1\n")

    def test_missing_token_stops_before_discovery_or_connection(self):
        self.args.token_file.unlink()
        for automatic in (True, False):
            with self.subTest(automatic=automatic):
                self.args.discover = automatic
                self.args.host = None if automatic else "192.0.2.1"
                with patch("voice_bridge.cli.discover_host") as find, patch(
                        "voice_bridge.cli.TcpLink") as link:
                    with self.assertRaisesRegex(RuntimeError, "passport-voice configure.*--wifi-ssid"):
                        open_session(self.args)
                    find.assert_not_called()
                    link.assert_not_called()

    def test_invalid_token_stops_before_discovery_or_connection(self):
        self.args.token_file.write_text("invalid")
        with patch("voice_bridge.cli.discover_host") as find, patch("voice_bridge.cli.TcpLink") as link:
            with self.assertRaises(ValueError):
                open_session(self.args)
            find.assert_not_called()
            link.assert_not_called()

    def test_usb_configuration_replaces_missing_token_without_changing_shortcut(self):
        self.args.token_file.unlink()
        self.args.serial = "/dev/cu.test"
        self.args.discover = False
        self.args.wifi_ssid = "test-network"
        self.args.shortcut = None
        with patch("voice_bridge.cli.SerialLink"), patch("voice_bridge.cli.Session") as session, patch(
                "voice_bridge.cli.getpass.getpass", return_value="test-password"):
            configure(self.args)
            saved = self.args.token_file.read_text().strip()
            self.assertEqual(len(saved), 64)
            self.assertEqual(self.args.token_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(session.return_value.request.call_args_list[0].args, ("hello",))
            self.assertEqual(session.return_value.request.call_args_list[0].kwargs, {"token": ""})
            request = session.return_value.request.call_args_list[1]
            self.assertEqual(request.args, ("configure",))
            self.assertEqual(request.kwargs,
                             {"ssid": "test-network", "password": "test-password", "token": saved})
            session.return_value.link.close.assert_called_once()
