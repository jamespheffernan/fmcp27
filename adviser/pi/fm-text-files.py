"""Create text files beneath approved roots using directory-relative OS calls."""
import json
import os
from pathlib import Path
import re
import sys


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def child_directory(parent, name, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
    return os.open(name, DIRECTORY_FLAGS, dir_fd=parent)


def write_text(params):
    path, content = params.get('path'), params.get('content')
    if not isinstance(path, str) or not path or '\0' in path:
        raise ValueError('Provide a file path.')
    if not isinstance(content, str) or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', content):
        raise ValueError('Content must be text without binary control characters.')
    data = content.encode('utf-8')
    if len(data) > 1_048_576:
        raise ValueError('Text files are limited to 1 MiB.')
    if Path(path).suffix.lower() not in ('.md', '.txt', '.csv'):
        raise ValueError('Use a .md, .txt or .csv filename.')

    project = Path(__file__).resolve().parent.parent
    home = Path.home().resolve()
    outputs = home / 'Agent Outputs'
    expanded = home / path[2:] if path.startswith('~/') else Path(path)
    target = Path(os.path.abspath(project / expanded))
    root = next((root for root in (project, outputs) if root in target.parents), None)
    if root is None:
        raise ValueError('Write only inside the pi-fm project or ~/Agent Outputs.')
    parts = target.relative_to(root).parts
    if any(part.startswith('.') or part == 'node_modules' for part in parts):
        raise ValueError('Hidden paths and dependency folders are not writable.')

    # Pin every ancestor to a directory descriptor; O_NOFOLLOW alone on the file
    # would still allow a concurrently replaced ancestor to redirect the write.
    parent = os.open('/', DIRECTORY_FLAGS)
    try:
        root_parts = root.parts[1:]
        for index, part in enumerate(root_parts):
            child = child_directory(parent, part, create=root == outputs and index == len(root_parts) - 1)
            os.close(parent)
            parent = child
        for part in parts[:-1]:
            child = child_directory(parent, part, create=True)
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data)
                file.flush()
                created = os.fstat(file.fileno())
                visible = os.stat(target, follow_symlinks=False)
                if (created.st_dev, created.st_ino) != (visible.st_dev, visible.st_ino):
                    raise OSError('Destination changed during file creation.')
        except BaseException:
            try:
                os.unlink(parts[-1], dir_fd=parent)
            except OSError:
                pass  # A relocated directory may now be outside the sandbox.
            raise
    finally:
        os.close(parent)
    return {'path': str(target), 'bytes': len(data), 'encoding': 'utf8'}


if __name__ == '__main__':
    try:
        print(json.dumps(write_text(json.load(sys.stdin))))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
