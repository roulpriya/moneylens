"""Private local storage for verified PDF passwords. No secret-bearing diagnostics."""
import hashlib
import os
from pathlib import Path
import tempfile
from .private_files import check_private, open_private, protect


class PrivateFiles:
    """Private skill state, protected by owner-only filesystem access; plaintext at rest."""
    def __init__(self, root):
        self.root = Path(root)
        if self.root.is_symlink(): raise ValueError('Credential directory must not be a symlink')
        created = not self.root.exists()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if created: protect(self.root, directory=True)
        self.check(self.root, 0o700, directory=True)

    @staticmethod
    def check(path, mode, directory=False):
        check_private(path, directory)

    def path(self, account):
        return self.root / (hashlib.sha256(account.encode()).hexdigest() + '.secret')

    def present(self, account):
        path = self.path(account)
        if not path.exists() and not path.is_symlink(): return False
        self.check(path, 0o600)
        return True

    def get(self, account, no_prompt=False):
        if not self.present(account): return None
        with open_private(self.path(account)) as stream: return stream.read(16384)

    def save(self, account, password):
        self.check(self.root, 0o700, directory=True)
        path = self.path(account)
        if path.exists() or path.is_symlink(): self.check(path, 0o600)
        fd, temporary = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                protect(temporary)
                stream.write(password)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def selected(data_dir):
    return PrivateFiles(Path(data_dir) / 'credentials')
