"""Start a local-only PostgreSQL container; never print or replace existing credentials."""

import json
import secrets
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
NAME = "before-open-postgres"
IMAGE = "postgres:17@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe"


def run(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def main() -> None:
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    existing = run("ps", "-a", "--filter", f"name=^/{NAME}$", "--format", "{{.Names}}")
    if existing:
        label = run("inspect", "--format", '{{index .Config.Labels "before-open.dev-db"}}', NAME)
        if label != "true" or not (LOCAL / "database-url").exists():
            raise RuntimeError("Existing container or local config is not owned by this setup")
        run("start", NAME)
    else:
        if (LOCAL / "database-url").exists() or (LOCAL / "postgres.env").exists():
            raise RuntimeError(
                "Preserving existing local credentials; restore their container first"
            )
        password = secrets.token_urlsafe(32)
        env_file = LOCAL / "postgres.env"
        with env_file.open("x") as stream:
            env_file.chmod(0o600)
            stream.write(
                f"POSTGRES_USER=beforeopen\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=beforeopen\n"
            )
        url_file = LOCAL / "database-url"
        with url_file.open("x") as stream:
            url_file.chmod(0o600)
            stream.write(f"postgresql+psycopg://beforeopen:{password}@127.0.0.1:5432/beforeopen")
        run(
            "run",
            "-d",
            "--name",
            NAME,
            "--label",
            "before-open.dev-db=true",
            "--env-file",
            str(env_file),
            "-p",
            "127.0.0.1:5432:5432",
            "--mount",
            "type=volume,source=before-open-pgdata,target=/var/lib/postgresql/data",
            IMAGE,
        )
    for _ in range(30):
        ready = subprocess.run(
            ["docker", "exec", NAME, "pg_isready", "-U", "beforeopen", "-d", "beforeopen"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if ready.returncode == 0:
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("Local PostgreSQL did not become ready")
    print(
        json.dumps(
            {"database": "local PostgreSQL", "container": NAME, "credentials": "not displayed"}
        )
    )


if __name__ == "__main__":
    main()
