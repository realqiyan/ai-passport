import socket
import time

class TcpLink:
    def __init__(self, host, connect_timeout=3):
        self.socket = None
        try:
            self.socket = socket.create_connection((host, 8765), timeout=connect_timeout)
            self.socket.settimeout(0.5)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as error:
            if self.socket is not None:
                self.socket.close()
            raise ConnectionError(f"Wi-Fi connection failed: {error}") from error

    def read(self):
        try:
            data = self.socket.recv(4096)
        except socket.timeout:
            return b""
        except OSError as error:
            raise ConnectionError(f"Wi-Fi read failed: {error}") from error
        if not data:
            raise ConnectionError("Device disconnected")
        return data

    def write(self, data):
        try:
            self.socket.sendall(data)
        except OSError as error:
            raise ConnectionError(f"Wi-Fi write failed: {error}") from error

    def close(self):
        self.socket.close()

class SerialLink:
    def __init__(self, port):
        import serial
        self.serial = serial.Serial()
        self.serial.port = port
        self.serial.baudrate = 115200  # USB Serial/JTAG ignores UART baudrate.
        self.serial.timeout = 0.5
        self.serial.write_timeout = 1
        self.serial.dtr = False
        self.serial.rts = False
        try:
            self.serial.open()
        except (OSError, serial.SerialException) as error:
            try:
                self.serial.close()
            except OSError:
                pass
            raise ConnectionError(f"USB open failed: {error}") from error

    def read(self):
        try:
            return self.serial.read(max(1, min(self.serial.in_waiting, 4096)))
        except OSError as error:
            raise ConnectionError(f"USB read failed: {error}") from error

    def write(self, data):
        view = memoryview(data)
        deadline = time.monotonic() + 1
        while view:
            try:
                written = self.serial.write(view)
            except OSError as error:
                raise ConnectionError(f"USB write failed: {error}") from error
            if not written or time.monotonic() >= deadline:
                raise TimeoutError("Incomplete serial write")
            view = view[written:]

    def close(self):
        self.serial.close()
