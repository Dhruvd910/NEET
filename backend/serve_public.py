"""Host the site from this computer so anyone on the internet can use it, through a Cloudflare quick tunnel.

    python serve_public.py

- Nothing is opened on your router or firewall: the site listens only on this computer (127.0.0.1) and
  `cloudflared` carries visitors' HTTPS traffic to it.
- The public site has its own data in backend/live/ (database and files), separate from development data.
- First run creates backend/.env.live with a random session secret. Keep that file private; it is git-ignored.
- Real data only: the official NMC college list (python -m app.maintenance import-colleges). No demo data is
  loaded. Create your admin account with: python -m app.maintenance create-admin --email you@example.com
- The address (https://….trycloudflare.com) is new every time this starts; it is printed and saved to
  backend/live/public_url.txt. Ctrl+C stops the site and the tunnel.

Needs `cloudflared` (winget install Cloudflare.cloudflared). Your OpenRouter key is read from backend/.env.
"""
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE / "live"
SECRETS = HERE / ".env.live"
PORT = int(os.environ.get("LIVE_PORT", "8780"))
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def live_secrets() -> dict[str, str]:
    if not SECRETS.exists():
        SECRETS.write_text(
            "# Secrets for the site hosted from this computer (serve_public.py). Never commit or share this file.\n"
            f"JWT_SECRET={secrets.token_urlsafe(48)}\n", encoding="utf-8")
        print(f"Created {SECRETS.name} (session secret).")
    pairs = (line.split("=", 1) for line in SECRETS.read_text(encoding="utf-8").splitlines()
             if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def find_cloudflared() -> str:
    exe = shutil.which("cloudflared") or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if not Path(exe).exists():
        sys.exit("cloudflared is not installed. Run: winget install Cloudflare.cloudflared")
    return exe


def start_tunnel() -> tuple[subprocess.Popen, str]:
    tunnel = subprocess.Popen([find_cloudflared(), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace")
    deadline = time.time() + 60
    for line in tunnel.stdout:
        if m := TUNNEL_URL.search(line):
            # Keep reading its log in the background so the pipe never fills up.
            threading.Thread(target=lambda: [None for _ in tunnel.stdout], daemon=True).start()
            return tunnel, m.group(0)
        if time.time() > deadline:
            break
    tunnel.kill()
    sys.exit("The Cloudflare tunnel did not start. Check your internet connection and try again.")


def wait_until_ready(url: str, proc: subprocess.Popen) -> None:
    for _ in range(180):
        if proc.poll() is not None:
            sys.exit("The site stopped while starting; see the messages above.")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/ready", timeout=2)
            return
        except OSError:
            time.sleep(1)
    sys.exit("The site did not become ready.")


def main() -> None:
    LIVE.mkdir(exist_ok=True)
    s = live_secrets()
    tunnel, url = start_tunnel()
    env = {
        **os.environ,
        "ENV": "staging",                     # production mode needs PostgreSQL + SMTP; this PC has neither
        "DATABASE_URL": f"sqlite:///{(LIVE / 'neet.db').as_posix()}",
        "STORAGE_DIR": str(LIVE / "storage"),
        "JWT_SECRET": s["JWT_SECRET"],
        "SEED_ON_START": "reference",         # courses, authorities, syllabus, info pages; never demo data
        "PLACES_PROVIDER": "overpass",        # admins can refresh a college's surroundings from OpenStreetMap
        "COOKIE_SECURE": "true",              # visitors always arrive over HTTPS through the tunnel
        "TRUST_PROXY_HEADERS": "true",        # safe: only the tunnel can reach 127.0.0.1
        "PUBLIC_APP_URL": url,
        "EMAIL_BACKEND": "console",
        "HOST": "127.0.0.1",
        "PORT": str(PORT),
    }
    site = subprocess.Popen([sys.executable, "start.py"], cwd=HERE, env=env)
    try:
        wait_until_ready(url, site)
        (LIVE / "public_url.txt").write_text(url + "\n", encoding="utf-8")
        print("\n" + "=" * 64 + f"\n  NEET Compass is live at:  {url}\n  Share this link. Keep this window open; Ctrl+C stops it.\n" + "=" * 64 + "\n")
        site.wait()
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        for p in (site, tunnel):
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
