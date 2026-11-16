"""Query-scoped, bounded, read-only transport to a single native task port."""
import json
import os
import select
import subprocess
import time


class ReaderError(RuntimeError):
    pass


class ReadStream:
    def __init__(self, helper, pid, timeout=45):
        self.helper, self.pid, self.timeout = helper, pid, timeout
        self.child = None
        self.closed = False

    def _response(self, command):
        deadline = time.monotonic() + self.timeout
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.child.stdout], [], [], remaining)[0]:
                raise ReaderError('Native read timed out; no result accepted.')
            chunk = os.read(self.child.stdout.fileno(), 4096)
            if not chunk:
                raise ReaderError('Native read stream closed before its response.')
            data.extend(chunk)
            if len(data) > 34000:
                raise ReaderError('Native read response exceeded its bound.')
            if b'\n' in data:
                if not data.endswith(b'\n') or data.count(b'\n') != 1:
                    raise ReaderError('Unexpected extra native response.')
                break
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ReaderError('Invalid native read response.') from exc
        if (not isinstance(result, dict) or result.get('ok') is not True
                or result.get('command') != command or result.get('pid') != self.pid):
            raise ReaderError('Native read failed or returned a mismatched response.')
        return result

    def read(self, address, length):
        if self.closed:
            raise ReaderError('Native read stream is closed.')
        if (type(address) is not int or type(length) is not int
                or not 1 <= length <= 16384 or not 0 < address < 2**64 - length):
            raise ReaderError('Invalid bounded memory read.')
        try:
            if self.child is None:
                self.child = subprocess.Popen(
                    [str(self.helper), 'read-stream', '--pid', str(self.pid)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0,
                )
                self._response('read-stream')
            self.child.stdin.write(f'{address} {length}\n'.encode('ascii'))
            result = self._response('read-bytes')
            if result.get('addr') != hex(address) or result.get('len') != length:
                raise ReaderError('Native read address or length disagrees.')
            data = bytes.fromhex(result['hex'])
            if len(data) != length:
                raise ReaderError('Incomplete native read.')
            return data
        except (OSError, ValueError, KeyError, TypeError, ReaderError) as exc:
            self.close()
            raise ReaderError(f'Native read stream rejected: {exc}') from exc

    def close(self):
        self.closed = True
        if self.child is None:
            return
        self.child.stdin.close()
        try:
            self.child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=5)
        finally:
            self.child.stdout.close()
