"""Check the device partition, then write and verify only the voice application."""
import argparse
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

APP_OFFSET = 0x10000


def check_application(image):
    if len(image) < 112 or image[0] != 0xE9:
        raise ValueError('Use FoloToy-AI-Passport.bin, not a merged image')
    if struct.unpack_from('<I', image, 32)[0] != 0xABCD5432:
        raise ValueError('Expected an ESP-IDF application, not a bootloader or merged image')
    if image[80:112].split(b'\0', 1)[0] != b'FoloToy-AI-Passport':
        raise ValueError('The application belongs to another project')
    if struct.unpack_from('<H', image, 12)[0] != 5:
        raise ValueError('The image is not for ESP32-C3')


def check_partition(table, image_size):
    if len(table) != 4096:
        raise ValueError('Incomplete partition table')
    found = []
    for offset in range(0, len(table), 32):
        magic = struct.unpack_from('<H', table, offset)[0]
        if magic in (0xFFFF, 0xEBEB):
            break
        if magic != 0x50AA:
            raise ValueError('Invalid partition table')
        _, kind, subtype, start, size, label, flags = struct.unpack_from('<HBBII16sI', table, offset)
        if kind == 0 and start == APP_OFFSET:
            if subtype != 0 or flags & 1:
                raise ValueError('The target must be an unencrypted factory application')
            if image_size > size:
                raise ValueError(f'Application exceeds the device partition: {image_size} > {size}')
            found.append(size)
    if len(found) != 1:
        raise ValueError('Expected exactly one factory application at 0x10000')
    return found[0]


def flash(port, firmware):
    # Hold a private copy so the image cannot change after its size is checked.
    image = firmware.read_bytes()
    check_application(image)
    base = [sys.executable, '-m', 'esptool', '--chip', 'esp32c3', '--port', port, '--baud', '460800']
    with tempfile.TemporaryDirectory(prefix='passport-voice-flash-') as directory:
        application = Path(directory) / 'application.bin'
        application.write_bytes(image)
        subprocess.run([sys.executable, '-m', 'esptool', '--chip', 'esp32c3',
                        'image_info', str(application)], check=True)
        table = Path(directory) / 'partitions.bin'
        subprocess.run(base + ['read_flash', '0x8000', '0x1000', str(table)], check=True)
        size = check_partition(table.read_bytes(), len(image))
        print(f'Write application only: {len(image)} / {size} bytes at 0x10000', flush=True)
        subprocess.run(base + ['write_flash', '0x10000', str(application)], check=True)
        subprocess.run(base + ['verify_flash', '0x10000', str(application)], check=True)


def list_ports():
    try:
        from serial.tools import list_ports as serial_ports
    except ImportError as error:
        raise RuntimeError('Activate ESP-IDF or install esptool==4.12.0 in this Python environment') from error
    ports = sorted(serial_ports.comports(), key=lambda port: port.device)
    if not ports:
        print('No serial ports found. Connect the device with a USB data cable.')
        return
    for port in ports:
        usb = (f' [USB {port.vid:04x}:{port.pid:04x}]'
               if port.vid is not None and port.pid is not None else '')
        print(f'{port.device}: {port.description}{usb}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list-ports', action='store_true',
                        help='List serial ports without opening or resetting the device')
    parser.add_argument('port', nargs='?', help='Explicit device serial port; stop the bridge first')
    parser.add_argument('firmware', nargs='?', type=Path, help='Application .bin, not the merged image')
    args = parser.parse_args(argv)
    if args.list_ports and (args.port is not None or args.firmware is not None):
        parser.error('--list-ports cannot be combined with a port or firmware')
    if not args.list_ports and (args.port is None or args.firmware is None):
        parser.error('Specify a port and firmware. Use --list-ports to find the device port.')
    try:
        if args.list_ports:
            list_ports()
        else:
            flash(args.port, args.firmware)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Flash failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
