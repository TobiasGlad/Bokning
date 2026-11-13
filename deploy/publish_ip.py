#!/usr/bin/env python3
"""Publish this existing installation on its host's IPv4 address (HTTP test use).

Run outside the restricted agent sandbox, as root. No account credentials are
included, generated or reset. --check performs read-only preparation checks.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / '.venv/bin/python'
AVAILABLE = Path('/etc/apache2/conf-available/bokning-ip.conf')
ENABLED = Path('/etc/apache2/conf-enabled/bokning-ip.conf')
SERVICE = Path('/etc/systemd/system/bokning.service')
PUBLIC_STATIC = Path('/var/www/bokning-static')


def apache_config():
    return '''# Managed by /root/bokning/deploy/publish_ip.py
# Global prefix route; existing VirtualHost definitions remain unchanged.
RedirectMatch 301 ^/bokning$ /bokning/
Alias /bokning/static/ /var/www/bokning-static/
<Directory /var/www/bokning-static>
    Require all granted
    Options -Indexes
</Directory>
ProxyPass /bokning/static/ !
ProxyPreserveHost On
ProxyPass /bokning/ http://127.0.0.1:8010/bokning/ timeout=120
ProxyPassReverse /bokning/ http://127.0.0.1:8010/bokning/
'''


def atomic_write(path, content, mode=0o600):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run(*command):
    subprocess.run([str(item) for item in command], cwd=ROOT, check=True)


def prerequisites():
    if not PYTHON.exists():
        raise RuntimeError('Installera projektets virtuella Python-miljö först enligt README.md.')
    if not (ROOT / '.secrets/settings.json').is_file():
        raise RuntimeError('Lokala inställningar saknas. Kör deploy/init_local.py först.')
    if not (ROOT / 'private/db.sqlite3').is_file():
        raise RuntimeError('Den privata installationsdatabasen saknas. Avbryter utan att skapa eller ändra konton.')
    for command in ['systemctl', 'apache2ctl', 'a2enmod', 'a2enconf']:
        if not shutil.which(command):
            raise RuntimeError(f'{command} saknas. Detta skript kräver Apache och systemd.')
    run(PYTHON, '-c', 'import django, gunicorn, PIL, requests, authlib, cryptography')


def private_settings(settings, address):
    values = dict(settings)
    hosts = [h.strip() for h in str(values.get('ALLOWED_HOSTS', '')).split(',') if h.strip() and h.strip() != '*']
    values.update(PUBLIC_ORIGIN=f'http://{address}',
        ALLOWED_HOSTS=','.join(dict.fromkeys([*hosts, address, 'localhost', '127.0.0.1'])),
        SECURE_COOKIES='false', SSL_REDIRECT='false', HSTS_SECONDS=0, TRUST_PROXY_HTTPS='false', DEBUG='false')
    return values


def publish(address):
    prerequisites()
    if os.geteuid() != 0:
        raise RuntimeError('Kör installationskommandot som root på servern.')
    secret_path = ROOT / '.secrets/settings.json'
    old_settings = secret_path.read_bytes()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = ROOT / 'private' / ('before-publish-' + stamp)
    backup.mkdir(mode=0o700)
    atomic_write(backup / 'settings.json', old_settings)
    database = ROOT / 'private/db.sqlite3'
    with sqlite3.connect(database) as source, sqlite3.connect(backup / 'db.sqlite3') as target:
        source.backup(target)
    (backup / 'db.sqlite3').chmod(0o600)
    old_conf = AVAILABLE.read_bytes() if AVAILABLE.exists() else None
    old_service = SERVICE.read_bytes() if SERVICE.exists() else None
    had_enabled = ENABLED.exists() or ENABLED.is_symlink()
    service_changed = False
    try:
        values = private_settings(json.loads(old_settings), address)
        atomic_write(secret_path, json.dumps(values, indent=2).encode())
        run(PYTHON, 'manage.py', 'check')
        run(PYTHON, 'manage.py', 'migrate', '--noinput')
        run(PYTHON, 'manage.py', 'collectstatic', '--noinput')
        # Copy only collected public assets. Private pictures are served by Django.
        PUBLIC_STATIC.mkdir(mode=0o755, parents=True, exist_ok=True)
        PUBLIC_STATIC.chmod(0o755)
        shutil.copytree(ROOT / 'staticfiles', PUBLIC_STATIC, dirs_exist_ok=True)
        for path in PUBLIC_STATIC.rglob('*'):
            path.chmod(0o755 if path.is_dir() else 0o644)
        run('a2enmod', 'alias', 'proxy', 'proxy_http')
        atomic_write(AVAILABLE, apache_config().encode(), 0o644)
        run('a2enconf', 'bokning-ip')
        run('apache2ctl', 'configtest')
        atomic_write(SERVICE, (ROOT / 'deploy/bokning.service').read_bytes(), 0o644)
        service_changed = True
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', 'bokning.service')
        run('systemctl', 'restart', 'bokning.service')
        run('systemctl', 'is-active', '--quiet', 'bokning.service')
        run('systemctl', 'reload', 'apache2')
        # Verify the actual proxy route, CSS, and denial of anonymous private data.
        for path in ['/bokning/login/', '/bokning/static/bokning/app.css']:
            request = Request('http://127.0.0.1' + path, headers={'Host': address})
            for attempt in range(10):
                try:
                    with urlopen(request, timeout=5) as response:
                        if response.status != 200:
                            raise RuntimeError('Webbkontrollen misslyckades: ' + path)
                    break
                except (URLError, OSError):
                    if attempt == 9:
                        raise RuntimeError('Webbkontrollen misslyckades: ' + path) from None
                    time.sleep(1)
        for path in ['/bokning/private/db.sqlite3', '/bokning/.secrets/settings.json']:
            request = Request('http://127.0.0.1' + path, headers={'Host': address})
            try:
                with urlopen(request, timeout=5):
                    raise RuntimeError('En privat sökväg svarade utan åtkomstskydd. Avbryter.')
            except HTTPError as exc:
                if exc.code != 404:
                    raise RuntimeError('Privat sökväg svarade inte med förväntad 404.') from None
        print(f'Publicerad och lokalt verifierad via Apache: http://{address}/bokning/')
        print('HTTP-testinstallation: telefoninstallation och externa inloggningar behöver HTTPS.')
        print('Befintliga användare och lösenord har bevarats. Privat backup:', backup)
    except Exception:
        # Restore routing/settings and leave a consistent database backup for recovery.
        atomic_write(secret_path, old_settings)
        if old_conf is None:
            AVAILABLE.unlink(missing_ok=True)
        else:
            atomic_write(AVAILABLE, old_conf, 0o644)
        if not had_enabled:
            ENABLED.unlink(missing_ok=True)
        if service_changed:
            subprocess.run(['systemctl', 'stop', 'bokning.service'], check=False)
            if old_service is None:
                subprocess.run(['systemctl', 'disable', 'bokning.service'], check=False)
                SERVICE.unlink(missing_ok=True)
            else:
                atomic_write(SERVICE, old_service, 0o644)
            subprocess.run(['systemctl', 'daemon-reload'], check=False)
            if old_service is not None:
                subprocess.run(['systemctl', 'restart', 'bokning.service'], check=False)
        check = subprocess.run(['apache2ctl', 'configtest'], check=False)
        if check.returncode == 0:
            subprocess.run(['systemctl', 'reload', 'apache2'], check=False)
        print('Publiceringen misslyckades. Tidigare inställningar och webbroute återställda.', file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('address', type=ipaddress.IPv4Address)
    parser.add_argument('--check', action='store_true', help='Kontrollera förutsättningar utan ändringar.')
    args = parser.parse_args()
    try:
        if args.check:
            prerequisites()
            print('Förutsättningar kontrollerade. Planerad adress: http://' + str(args.address) + '/bokning/')
            print('Ingen tjänst, webbroute, databas eller privat inställning har ändrats.')
        else:
            publish(str(args.address))
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, 'Fel: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
