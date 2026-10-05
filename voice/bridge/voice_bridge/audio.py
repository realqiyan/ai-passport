"""Keep playback memory and latency bounded."""
from collections import deque
import threading

class AudioBuffer:
    def __init__(self, max_chunks=8):
        self.chunks = deque()
        self.max_chunks = max_chunks
        self.lock = threading.Lock()
        self.drops = 0
        self.underruns = 0
        self.last_sequence = None
        self.gaps = 0
        self.pending = b""

    def push(self, sequence, pcm):
        if len(pcm) != 640:
            raise ValueError("Expected 320 mono int16 samples")
        stereo = b"".join(pcm[i:i+2] * 2 for i in range(0, len(pcm), 2))
        with self.lock:
            if self.last_sequence is not None:
                expected = (self.last_sequence + 1) & 0xffffffff
                if sequence != expected:
                    self.gaps += 1
            self.last_sequence = sequence
            if len(self.chunks) >= self.max_chunks:
                self.chunks.popleft()
                self.drops += 1
            self.chunks.append(stereo)

    def clear(self):
        with self.lock:
            self.chunks.clear()
            self.pending = b""
            self.last_sequence = None

    def read(self, size):
        with self.lock:
            result = bytearray()
            while len(result) < size:
                if not self.pending:
                    if not self.chunks:
                        self.underruns += 1
                        result.extend(bytes(size - len(result)))
                        break
                    self.pending = self.chunks.popleft()
                take = min(size - len(result), len(self.pending))
                result.extend(self.pending[:take])
                self.pending = self.pending[take:]
            return bytes(result)

class AudioSink:
    def __init__(self, output):
        import sounddevice as sd
        self.sd = sd
        self.buffer = AudioBuffer()
        # Select a virtual output explicitly. Never fall back to speakers.
        devices = sd.query_devices()
        if output.isdecimal():
            candidates = [int(output)] if int(output) < len(devices) else []
        else:
            candidates = [i for i, d in enumerate(devices)
                          if output.casefold() in d["name"].casefold() and d["max_output_channels"] >= 2]
        if len(candidates) != 1:
            raise ValueError("Choose exactly one output with 'passport-voice devices'")
        device = candidates[0]
        if devices[device]["max_output_channels"] < 2:
            raise ValueError("Output must support two channels")
        sd.check_output_settings(device=device, channels=2, dtype="int16", samplerate=16000)
        self.stream = sd.RawOutputStream(device=device, samplerate=16000,
            channels=2, dtype="int16", blocksize=320, callback=self.callback)

    def callback(self, outdata, frames, timing, status):
        outdata[:] = self.buffer.read(frames * 4)

    def start(self):
        self.stream.start()

    def close(self):
        self.stream.stop()
        self.stream.close()
