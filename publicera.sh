#!/usr/bin/env bash
# Publicera Bokning via serverns IP. Inga användaruppgifter ingår i skriptet.
set -Eeuo pipefail
umask 077

bokning_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bokning_address="82.165.46.250"
bokning_check=false
bokning_step="förberedelser"

usage() {
    printf 'Användning: bash %s [IP-adress] [--check]\n' "$0"
    printf 'Exempel: bash %s 82.165.46.250\n' "$0"
    printf '%s\n' '--check kontrollerar utan att ändra installationen.'
}

for bokning_argument in "$@"; do
    case "$bokning_argument" in
        --check) bokning_check=true ;;
        --help|-h) usage; exit 0 ;;
        --*) usage >&2; exit 2 ;;
        *) bokning_address="$bokning_argument" ;;
    esac
done

fail() {
    printf '\nFEL: %s\n' "$1" >&2
    exit 1
}

diagnostics() {
    local bokning_status="$?"
    trap - ERR
    printf '\nPubliceringen stoppades under: %s (felkod %s).\n' "$bokning_step" "$bokning_status" >&2
    if [[ "$bokning_check" == false ]] && command -v systemctl >/dev/null 2>&1; then
        printf '\nStatus för Bokning:\n' >&2
        systemctl --no-pager --full status bokning.service >&2 || true
        printf '\nSenaste händelser för Bokning:\n' >&2
        journalctl --no-pager -u bokning.service -n 25 >&2 || true
    fi
    printf '\nKopiera felmeddelandet ovan om du behöver hjälp. Inga konton eller lösenord återställs.\n' >&2
    exit "$bokning_status"
}
trap diagnostics ERR

command -v python3 >/dev/null 2>&1 || fail 'python3 saknas på servern.'
python3 -c 'import ipaddress, sys; ipaddress.IPv4Address(sys.argv[1])' "$bokning_address" \
    || fail 'Ange en giltig IPv4-adress.'
[[ -f "$bokning_root/manage.py" && -f "$bokning_root/deploy/publish_ip.py" ]] \
    || fail 'Skriptet ska ligga i projektmappen tillsammans med manage.py och deploy/publish_ip.py.'

if [[ "$bokning_check" == false && "$EUID" -ne 0 ]]; then
    fail "Kör som root: sudo bash $bokning_root/publicera.sh $bokning_address"
fi
for bokning_command in systemctl apache2ctl a2enmod a2enconf; do
    command -v "$bokning_command" >/dev/null 2>&1 \
        || fail "$bokning_command saknas. Servern behöver Apache och systemd."
done

cd -- "$bokning_root"
bokning_python="$bokning_root/.venv/bin/python"
if [[ "$bokning_check" == true ]]; then
    [[ -x "$bokning_python" ]] || fail 'Python-miljön saknas. Kör utan --check för att skapa den.'
    "$bokning_python" deploy/publish_ip.py "$bokning_address" --check
    exit 0
fi

# Verify service access before touching private settings or installing packages.
bokning_step="åtkomst till serverns tjänster"
systemctl show --property=Version --value >/dev/null \
    || fail 'Kan inte nå systemd. Kör skriptet i serverns vanliga SSH-/Plesk-terminal, inte inne i agentens begränsade körmiljö.'

bokning_step="Python-miljö och paket"
if [[ ! -x "$bokning_python" ]]; then
    printf 'Skapar Python-miljö i %s/.venv ...\n' "$bokning_root"
    python3 -m venv "$bokning_root/.venv" \
        || fail 'Kunde inte skapa Python-miljön. Installera python3-venv på servern och kör igen.'
fi
if ! "$bokning_python" -c 'import django, gunicorn, PIL, requests, authlib, cryptography' >/dev/null 2>&1; then
    printf 'Installerar projektets Python-paket ...\n'
    "$bokning_python" -m pip install -r requirements.txt
fi

# Never silently replace a missing existing database or regenerate its key.
[[ -f .secrets/settings.json ]] || fail 'Privata inställningar saknas. Återställ .secrets/settings.json från installationen innan publicering.'
[[ -f private/db.sqlite3 ]] || fail 'Den privata databasen saknas. Återställ private/db.sqlite3 för att bevara administratörskontot.'

bokning_step="förkontroll"
"$bokning_python" deploy/publish_ip.py "$bokning_address" --check

bokning_step="Apache, systemd och webbkontroll"
printf '\nPublicerar Bokning under /bokning/ på %s ...\n' "$bokning_address"
"$bokning_python" deploy/publish_ip.py "$bokning_address"

printf '\nKLART. Den verifierade adressen visas ovan (HTTPS används när IP-värden har det).\n'
printf '%s\n' 'Befintliga konton och lösenord är bevarade.'
