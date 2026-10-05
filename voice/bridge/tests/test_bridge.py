import json
import argparse
import struct
import unittest
from voice_bridge.protocol import encode, Parser, PCM, STATUS
from voice_bridge.audio import AudioBuffer
from voice_bridge.cli import Session, shortcut

class ProtocolTests(unittest.TestCase):
    def test_corruption_and_fragmentation(self):
        packet = encode(PCM, 42, b"abc")
        self.assertEqual(packet.hex(), "56503031010003002a000000f972e58d616263")
        parser = Parser()
        result = []
        corrupt = bytearray(packet)
        corrupt[-1] ^= 1
        for byte in b"boot log\n" + bytes(corrupt) + packet * 2:
            result += parser.feed(bytes([byte]))
        self.assertEqual([f.payload for f in result], [b"abc", b"abc"])
        self.assertEqual(result[0].sequence, 42)
        self.assertGreater(parser.errors, 0)

    def test_limit_and_long_noise(self):
        parser = Parser()
        self.assertEqual(parser.feed(b"X" * 100000), [])
        self.assertLessEqual(len(parser.buffer), 3)
        bad = bytearray(encode(PCM, 42, b"abc"))
        bad[6:8] = b"\xff\xff"
        self.assertEqual(len(parser.feed(bytes(bad) + encode(PCM, 42, b"abc"))), 1)
        with self.assertRaises(ValueError):
            encode(PCM, 0, b"x" * 1025)

    def test_stereo_silence_and_capacity(self):
        buf = AudioBuffer(max_chunks=2)
        pcm = struct.pack("<h", 123) * 320
        for sequence in (0, 1, 3):
            buf.push(sequence, pcm)
        self.assertEqual(buf.drops, 1)
        self.assertEqual(buf.gaps, 1)
        self.assertEqual(buf.read(8), struct.pack("<h", 123) * 4)
        buf.clear()
        self.assertEqual(buf.read(1280), bytes(1280))
        with self.assertRaises(ValueError):
            buf.push(4, b"bad")

    def test_sequence_wrap(self):
        buf = AudioBuffer()
        for sequence in (0xffffffff, 0):
            buf.push(sequence, bytes(640))
        self.assertEqual(buf.gaps, 0)

    def test_acknowledgement_and_shortcut(self):
        class Link:
            def write(self, data):
                self.sequence = Parser().feed(data)[0].sequence
            def read(self):
                return encode(STATUS, 0, json.dumps({"ack": self.sequence, "result": "ok"}).encode())
        self.assertEqual(Session(Link()).request("hello")["result"], "ok")
        self.assertEqual(shortcut("ctrl+alt+space"), (5, 44))
        with self.assertRaises(argparse.ArgumentTypeError):
            shortcut("fn")

if __name__ == "__main__":
    unittest.main()
