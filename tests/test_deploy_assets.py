from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "deploy/systemd/devils-committee.service"
NGINX_TEMPLATE = ROOT / "deploy/nginx/devils-committee.conf.template"
RENDER_SCRIPT = ROOT / "scripts/render_nginx_config.sh"
DEPLOY_CHECK_SCRIPT = ROOT / "scripts/deploy_check.sh"


def test_systemd_service_uses_persistent_runtime_and_hardening() -> None:
    text = SERVICE.read_text(encoding="utf-8")

    assert "User=devils" in text
    assert "Group=devils" in text
    assert "EnvironmentFile=/etc/devils-committee/devils-committee.env" in text
    assert "Environment=CACHE_DIR=/var/lib/devils-committee/cache" in text
    assert "Environment=PRECOMPUTED_DIR=/var/lib/devils-committee/precomputed" in text
    assert (
        "ExecStart=/opt/devils-committee/.venv-real/bin/uvicorn "
        "backend.a2a_server:app --host 127.0.0.1 --port 18080 --workers 1"
    ) in text
    assert "Restart=always" in text
    assert "NoNewPrivileges=true" in text
    assert "PrivateTmp=true" in text
    assert "ProtectSystem=strict" in text
    assert "ProtectHome=true" in text
    assert "ReadWritePaths=/var/lib/devils-committee" in text

    for secret_name in ("A2A_BEARER_TOKEN", "LLM_API_KEY", "PANDA_PASSWORD"):
        assert f"{secret_name}=" not in text


def test_nginx_template_proxies_public_routes_without_embedded_secrets() -> None:
    text = NGINX_TEMPLATE.read_text(encoding="utf-8")

    assert "listen 443 ssl http2;" in text
    assert "listen 80;" in text
    assert "server_name ${PUBLIC_HOST};" in text
    assert "/etc/letsencrypt/live/${PUBLIC_HOST}/fullchain.pem" in text
    assert "/etc/letsencrypt/live/${PUBLIC_HOST}/privkey.pem" in text
    assert "client_max_body_size 2m;" in text
    assert "proxy_pass http://127.0.0.1:18080;" in text
    assert "proxy_read_timeout 610s;" in text
    assert "proxy_send_timeout 610s;" in text
    assert "proxy_buffering off;" in text
    assert "proxy_set_header Host $host;" in text
    assert "proxy_set_header X-Forwarded-Proto https;" in text
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in text
    assert "return 301 https://$host$request_uri;" in text
    assert "Authorization" not in text
    assert "LLM_API_KEY" not in text


def _fake_envsubst(bin_dir: Path) -> None:
    executable = bin_dir / "envsubst"
    executable.write_text(
        """#!/usr/bin/env python3
import os
import sys

text = sys.stdin.read()
sys.stdout.write(text.replace("${PUBLIC_HOST}", os.environ["PUBLIC_HOST"]))
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def test_render_script_renders_a_valid_hostname(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_envsubst(fake_bin)
    output = tmp_path / "rendered" / "devils-committee.conf"
    env = os.environ.copy()
    env.update(
        {
            "PUBLIC_HOST": "a2a.example.com",
            "OUTPUT_PATH": str(output),
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
        }
    )

    result = subprocess.run(
        ["bash", str(RENDER_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    rendered = output.read_text(encoding="utf-8")
    assert "server_name a2a.example.com;" in rendered
    assert "/etc/letsencrypt/live/a2a.example.com/fullchain.pem" in rendered
    assert "${PUBLIC_HOST}" not in rendered


@pytest.mark.parametrize(
    "hostname",
    [
        "",
        ".example.com",
        "example.com.",
        "bad..example.com",
        "-example.com",
        "example-.com",
        "bad/host",
        "bad_host",
        "example.com:443",
        "--help",
    ],
)
def test_render_script_rejects_invalid_hostname(tmp_path: Path, hostname: str) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_envsubst(fake_bin)
    output = tmp_path / "devils-committee.conf"
    env = os.environ.copy()
    env.update(
        {
            "PUBLIC_HOST": hostname,
            "OUTPUT_PATH": str(output),
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
        }
    )

    result = subprocess.run(
        ["bash", str(RENDER_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert not output.exists()


def test_deploy_check_runs_public_smoke_and_read_only_endpoint_checks() -> None:
    text = DEPLOY_CHECK_SCRIPT.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert '${PUBLIC_URL:?' in text
    assert "python3 scripts/smoke_a2a.py" in text
    assert '--url "$PUBLIC_URL"' in text
    assert '--token "${A2A_BEARER_TOKEN:-}"' in text
    assert '--ticker "600519.SH 多空证据和风险"' in text
    assert 'curl --fail --silent --show-error "$PUBLIC_URL/healthz"' in text
    assert (
        'curl --fail --silent --show-error '
        '"$PUBLIC_URL/.well-known/agent-card.json"'
    ) in text
    assert "echo" not in text


@pytest.mark.parametrize("script", [RENDER_SCRIPT, DEPLOY_CHECK_SCRIPT])
def test_deployment_shell_scripts_are_executable(script: Path) -> None:
    assert script.stat().st_mode & stat.S_IXUSR
