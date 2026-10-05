import json
import socket
import threading
import unittest
from voice_bridge.cli import Session
from voice_bridge.protocol import COMMAND, PCM, STATUS, Parser, encode
from voice_bridge.transport import TcpLink

class SessionTests(unittest.TestCase):
    def test_coalesced_ack_preserves_audio(self):
        class Link:
            def write(self, packet):
                self.sequence = Parser().feed(packet)[0].sequence
            def read(self):
                status = json.dumps({"ack": self.sequence, "result": "ok"}).encode()
                return encode(STATUS, 0, status) + encode(PCM, 7, bytes(640))
        session = Session(Link())
        session.request("hello")
        self.assertEqual(session.receive()[0].sequence, 7)

    def test_rejected_command(self):
        class Link:
            def write(self, packet):
                self.sequence = Parser().feed(packet)[0].sequence
            def read(self):
                return encode(STATUS, 0, json.dumps({"ack": self.sequence, "result": "invalid configuration"}).encode())
        with self.assertRaisesRegex(RuntimeError, "invalid configuration"):
            Session(Link()).request("configure")

    def test_tcp_authentication_and_partial_frames(self):
        # TcpLink connects to the firmware's fixed port. Mock create_connection
        # to select an ephemeral local server, without replacing socket behavior.
        from unittest.mock import patch
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(2)
        endpoint = server.getsockname()
        errors = []
        def device():
            try:
                client, _ = server.accept()
                with client:
                    client.settimeout(2)
                    parser = Parser()
                    while True:
                        data = client.recv(4096)
                        if not data:
                            break
                        frames = parser.feed(data)
                        if not frames:
                            continue
                        frame = frames[0]
                        self.assertEqual(frame.kind, COMMAND)
                        self.assertEqual(json.loads(frame.payload)["token"], "test-token")
                        reply = encode(STATUS, 0, json.dumps({"ack": frame.sequence, "result": "ok"}).encode())
                        client.sendall(reply[:9])
                        client.sendall(reply[9:])
                        break
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=device)
        thread.start()
        real_connect = socket.create_connection
        try:
            with patch("voice_bridge.transport.socket.create_connection", side_effect=lambda addr, timeout: real_connect(endpoint, timeout)):
                link = TcpLink("127.0.0.1")
            try:
                self.assertEqual(Session(link).request("hello", token="test-token")["result"], "ok")
            finally:
                link.close()
        finally:
            thread.join(3)
            server.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

if __name__ == "__main__":
    unittest.main()
