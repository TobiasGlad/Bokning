"""Create private keys. No user credentials are included in this script."""
import json
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parent.parent
folder = root / '.secrets'
folder.mkdir(mode=0o700, exist_ok=True)
target = folder / 'settings.json'
if not target.exists():
    with target.open('x') as handle:
        target.chmod(0o600)
        json.dump({'SECRET_KEY': secrets.token_urlsafe(64), 'TOKEN_ENCRYPTION_KEY': Fernet.generate_key().decode()}, handle)
(root / 'private').mkdir(mode=0o700, exist_ok=True)
print('Lokala nycklar klara. Inga konton eller lösenord har skapats av skriptet.')
