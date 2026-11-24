"""Выкатка дашборда на российский VPS.

Запуск с машины разработчика:

    python dashboard/deploy.py                # обычное обновление
    python dashboard/deploy.py --init-env     # первый раз: создать .env из локального

Скрипт копирует код архивом, ставит зависимости и перезапускает сервис.
Файл `.env` на сервере НЕ перезаписывается: там лежит read-only токен GitHub,
а локальный `.env` содержит полный токен бота, и подмена сломала бы разделение
прав. Создать `.env` из локального можно только явным флагом --init-env.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = ("config.py", "prompts.py", "services", "dashboard")
TARGET = "/opt/obsidian-dashboard"

REMOTE = r"""
set -e

if ! id obsidian-dash >/dev/null 2>&1; then
  useradd --system --home-dir TARGET --shell /usr/sbin/nologin --user-group obsidian-dash
fi

mkdir -p TARGET
tar -xzf /tmp/dash.tgz -C TARGET
chown -R obsidian-dash:obsidian-dash TARGET

if [ ! -x TARGET/.venv/bin/python ]; then
  python3 -m venv TARGET/.venv
fi
TARGET/.venv/bin/pip install -q --upgrade pip wheel
TARGET/.venv/bin/pip install -q -r TARGET/dashboard/requirements.txt

if [ "$INIT_ENV" = "1" ]; then
  install -m 600 -o obsidian-dash -g obsidian-dash /tmp/dash.env TARGET/.env
  echo "env: создан из локального .env"
  rm -f /tmp/dash.env
elif [ -f TARGET/.env ]; then
  echo "env: оставлен прежний (не перезаписываем)"
else
  echo "env: НЕ НАЙДЕН. Запусти с --init-env" >&2
  exit 1
fi

install -m 644 TARGET/dashboard/obsidian-dashboard.service \
  /etc/systemd/system/obsidian-dashboard.service
systemctl daemon-reload
systemctl enable obsidian-dashboard >/dev/null 2>&1
systemctl restart obsidian-dashboard
sleep 4

echo "health: $(curl -sS -m 20 http://127.0.0.1:8000/healthz)"
systemctl is-active obsidian-dashboard
journalctl -u obsidian-dashboard -n 4 --no-pager | sed 's/^/  /'
rm -f /tmp/dash.tgz
"""


def build_archive(dest: Path) -> None:
    def skip(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(info.name).parts
        if "__pycache__" in parts or info.name.endswith(".pyc"):
            return None
        return info

    with tarfile.open(dest, "w:gz") as tar:
        for name in PAYLOAD:
            path = ROOT / name
            if not path.exists():
                raise SystemExit(f"нет файла или папки: {name}")
            tar.add(path, arcname=name, filter=skip)


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Выкатить дашборд на VPS")
    parser.add_argument(
        "--host",
        default="cloudfern",
        help="SSH-алиас из ~/.ssh/config (по умолчанию cloudfern)",
    )
    parser.add_argument(
        "--init-env",
        action="store_true",
        help="создать .env на сервере из локального файла (только при первой установке)",
    )
    args = parser.parse_args()

    if args.init_env and not (ROOT / ".env").exists():
        print("нет локального .env — создавать нечего", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "dash.tgz"
        build_archive(archive)
        print(f"архив: {archive.stat().st_size} байт")

        run(["scp", "-q", str(archive), f"{args.host}:/tmp/dash.tgz"])
        if args.init_env:
            text = (ROOT / ".env").read_text(encoding="utf-8").replace("\r\n", "\n")
            env_file = Path(tmp) / "dash.env"
            env_file.write_text(text, encoding="utf-8", newline="\n")
            run(["scp", "-q", str(env_file), f"{args.host}:/tmp/dash.env"])

    script = (
        REMOTE.replace("TARGET", TARGET)
        .replace('"$INIT_ENV"', '"1"' if args.init_env else '"0"')
    )
    try:
        run(["ssh", args.host, "bash -s"], input=script.encode("utf-8"))
    except subprocess.CalledProcessError as exc:
        print(f"выкатка не удалась, код {exc.returncode}", file=sys.stderr)
        return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
