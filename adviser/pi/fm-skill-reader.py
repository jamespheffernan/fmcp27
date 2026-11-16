"""Read one caller-approved guide through a no-follow descriptor lineage.

The public catalogue and trusted root configuration belong to fm-skills.mjs.
This helper has no arbitrary filename operation: the leaf is always SKILL.md.
"""
import hashlib
import json
import os
import re
import stat
import sys

MAX_BYTES = 65536
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def identity(info):
    return info.st_dev, info.st_ino, info.st_mode


def file_state(info):
    return identity(info) + (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def valid_guide_identity(content, guide_id):
    if not isinstance(content, str) or not isinstance(guide_id, str) or not content.startswith('---\n'):
        return False
    # The bundled format permits LF and printable text, not hidden metadata
    # lines introduced by control bytes or alternate Unicode separators.
    if re.search(r'[\x00-\x09\x0b-\x1f\x7f-\x9f\u2028\u2029]', content):
        return False
    lines = content.split('\n')
    try:
        end = lines.index('---', 1)
    except ValueError:
        return False
    names = []
    # Match the bundled flat, unquoted-key format; ambiguous YAML constructs
    # fail closed instead of acquiring a second interpretation of "name".
    for line in lines[1:end]:
        if not line or line.startswith('#'):
            continue
        field = re.fullmatch(r'([a-z][a-z0-9_-]*):(?: ([^\n]*))?', line)
        if field is None:
            return False
        value = (field.group(2) or '').lstrip(' ')
        # Canonical plain scalars start with an ASCII letter/digit, excluding
        # quoted, block, flow, tag, anchor and hidden-prefix scalar forms.
        if value and re.match(r'[A-Za-z0-9]', value) is None:
            return False
        if re.search(r':(?: |$)', value):
            return False
        if field.group(1) == 'name':
            names.append(field.group(2))
    return names == [guide_id]


def check_lineage(lineage):
    for parent, name, child, expected in lineage:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or identity(current) != expected or identity(os.fstat(child)) != expected:
            raise ValueError('Guide directory binding changed')


def read_guide(root, guide_id):
    if (not isinstance(root, str) or not os.path.isabs(root) or root != os.path.normpath(root)
            or not isinstance(guide_id, str) or re.fullmatch(r'fm-[a-z]+(?:-[a-z]+)*', guide_id) is None):
        raise ValueError('Expected configured absolute root and approved guide id')
    descriptors = []
    lineage = []
    try:
        parent = os.open('/', DIRECTORY_FLAGS)
        descriptors.append(parent)
        for component in [part for part in root.split('/') if part] + [guide_id]:
            before = os.stat(component, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ValueError('Guide path must contain regular directories')
            child = os.open(component, DIRECTORY_FLAGS, dir_fd=parent)
            descriptors.append(child)
            expected = identity(os.fstat(child))
            if expected != identity(before):
                raise ValueError('Guide directory changed during opening')
            lineage.append((parent, component, child, expected))
            parent = child
        check_lineage(lineage)
        before = os.stat('SKILL.md', dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ValueError('Expected bounded regular guide file')
        leaf = os.open('SKILL.md', FILE_FLAGS, dir_fd=parent)
        descriptors.append(leaf)
        if file_state(os.fstat(leaf)) != file_state(before):
            raise ValueError('Guide file changed during opening')
        chunks = []
        size = 0
        while size <= MAX_BYTES:
            chunk = os.read(leaf, MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        raw = b''.join(chunks)
        after = os.fstat(leaf)
        current = os.stat('SKILL.md', dir_fd=parent, follow_symlinks=False)
        if (size > MAX_BYTES or size != before.st_size or file_state(after) != file_state(before)
                or file_state(current) != file_state(before)):
            raise ValueError('Guide changed during reading')
        check_lineage(lineage)
        content = raw.decode('utf-8', errors='strict')
        if not valid_guide_identity(content, guide_id):
            raise ValueError('Guide identity mismatch')
        result = {'content': content, 'sha256': hashlib.sha256(raw).hexdigest()}
    finally:
        # A failed close also withholds the result. Attempt every remaining close.
        close_error = None
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError as error:
                close_error = error
        if close_error is not None:
            raise close_error
    return result


def main():
    try:
        if len(sys.argv) != 3:
            raise ValueError('Expected configured root and approved guide id')
        result = read_guide(sys.argv[1], sys.argv[2])
    except (OSError, ValueError):
        # Filesystem exception strings can include attacker-controlled names.
        sys.stderr.write('Guide unavailable or changed during reading.\n')
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
