"""Bounded, checksummed frames shared with the ESP32 firmware."""
from dataclasses import dataclass
import struct
import zlib
MAGIC = b"VP01"
HEADER = struct.Struct("<4sBBHII")
MAX_PAYLOAD = 1024
PCM, COMMAND, STATUS = 1, 2, 3

@dataclass(frozen=True)
class Frame:
    kind: int
    sequence: int
    payload: bytes

def encode(kind: int, sequence: int, payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("Payload exceeds 1024 bytes")
    prefix = struct.pack("<4sBBHI", MAGIC, kind, 0, len(payload), sequence & 0xffffffff)
    checksum = zlib.crc32(prefix + payload)
    return prefix + struct.pack("<I", checksum) + payload

class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, data: bytes):
        # Feed bounded pieces so caller input cannot grow the working buffer.
        frames = []
        for start in range(0, len(data), 256):
            self.buffer.extend(data[start:start + 256])
            while True:
                offset = self.buffer.find(MAGIC)
                if offset < 0:
                    del self.buffer[:-3]
                    break
                if offset:
                    del self.buffer[:offset]
                if len(self.buffer) < HEADER.size:
                    break
                _, kind, flags, size, sequence, checksum = HEADER.unpack_from(self.buffer)
                if size > MAX_PAYLOAD or flags:
                    del self.buffer[0]
                    self.errors += 1
                    continue
                total = HEADER.size + size
                if len(self.buffer) < total:
                    break
                payload = bytes(self.buffer[HEADER.size:total])
                if zlib.crc32(bytes(self.buffer[:12]) + payload) != checksum:
                    del self.buffer[0]
                    self.errors += 1
                    continue
                frames.append(Frame(kind, sequence, payload))
                del self.buffer[:total]
        return frames
