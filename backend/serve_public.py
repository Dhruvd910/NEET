"""Host the site from this computer so anyone on the internet can use it.

    python serve_public.py              # Cloudflare quick tunnel (fast in India); a new address every start
    python serve_public.py --tailscale  # Tailscale Funnel: a fixed address, but slow or unreachable from India

The Cloudflare address changes on every start, so the launcher publishes it to a fixed link on GitHub Pages
(https://dhruvd910.github.io/NEET/, the gh-pages branch, checked out in backend/live/pages). Share that link.

- Nothing is opened on your router or firewall: the site listens only on this computer (127.0.0.1) and the
  tunnel (Tailscale Funnel or `cloudflared`) carries visitors' HTTPS traffic to it.
- The public site has its own data in backend/live/ (database and files), separate from development data.
- First run creates backend/.env.live with a random session secret. Keep that file private; it is git-ignored.
  Put other secrets for the public site there too, e.g. GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET for Google sign-in.
- Real data only: the official NMC college list (python -m app.maintenance import-colleges). No demo data is
  loaded. Create your admin account with: python -m app.maintenance create-admin --email you@example.com
- Tailscale gives a fixed address named after this PC (https://neet-compass.<tailnet>.ts.net). A quick tunnel's
  address (https://….trycloudflare.com) changes every start. Either way it is printed and saved to
  backend/live/public_url.txt. Ctrl+C stops the site (and the Cloudflare tunnel).

Needs Tailscale (signed in, Funnel allowed) or `cloudflared`. Your OpenRouter key is read from backend/.env.
"""
import json
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


TAILSCALE = r"C:\Program Files\Tailscale\tailscale.exe"


def tailscale_url() -> str | None:
    """This PC's fixed Funnel address, or None when Tailscale is not installed or not signed in."""
    exe = shutil.which("tailscale") or TAILSCALE
    if not Path(exe).exists():
        return None
    status = {}
    for _ in range(36):  # just after Windows starts, Tailscale can take a minute or two to connect
        try:
            status = json.loads(subprocess.run([exe, "status", "--json"], capture_output=True, text=True,
                                               timeout=20).stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            status = {}
        if status.get("BackendState") == "Running":
            break
        if status.get("BackendState") in ("NeedsLogin", "Stopped"):
            return None  # signed out or switched off: use the Cloudflare quick tunnel instead
        time.sleep(5)
    if status.get("BackendState") != "Running":
        return None
    # Funnel stays on across restarts (--bg); running it again is harmless and repairs a missing setting.
    subprocess.run([exe, "funnel", "--bg", "--yes", str(PORT)], capture_output=True, timeout=30)
    return "https://" + status["Self"]["DNSName"].rstrip(".")


PAGES = LIVE / "pages"  # git worktree of the gh-pages branch: the fixed link
FIXED_LINK = "https://dhruvd910.github.io/NEET/"


def publish_link(url: str) -> None:
    """Point the fixed GitHub Pages link at the site's current address. Failures are reported, never fatal."""
    if not (PAGES / ".git").exists():
        print("The fixed link is not set up (backend/live/pages is missing); share the address above instead.")
        return
    current = PAGES / "current.json"
    try:
        if json.loads(current.read_text(encoding="utf-8")).get("url") == url:
            return
    except (OSError, ValueError):
        pass
    current.write_text(json.dumps({"url": url, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n",
                       encoding="utf-8")
    git = ["git", "-C", str(PAGES), "-c", "user.name=Dhruvd910", "-c", "user.email=dhruvd910@gmail.com"]
    try:
        subprocess.run(git + ["add", "current.json"], check=True, capture_output=True, timeout=30)
        subprocess.run(git + ["commit", "-m", "Point the link at the current address"], check=True,
                       capture_output=True, timeout=30)
        subprocess.run(git + ["push", "origin", "gh-pages"], check=True, capture_output=True, timeout=120)
        print(f"Fixed link updated: {FIXED_LINK} (GitHub takes about a minute to publish it).")
    except (subprocess.SubprocessError, OSError) as e:
        print(f"Could not update the fixed link ({e}); share the address above instead.")


def public_ok(url: str) -> bool:
    try:
        urllib.request.urlopen(f"{url}/api/ready", timeout=20)
        return True
    except OSError:
        return False


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
    url = tailscale_url() if "--tailscale" in sys.argv else None
    tunnel = None
    if url is None:
        tunnel, url = start_tunnel()
    # Everything else in .env.live (e.g. GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET) is passed to the site as is.
    env = {
        **os.environ,
        **{k: v for k, v in s.items() if v},
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
        print("\n" + "=" * 64 + f"\n  NEET Compass is live at:  {url}\n  Share the fixed link:     {FIXED_LINK}\n"
              "  Keep this window open; Ctrl+C stops it.\n" + "=" * 64 + "\n")
        publish_link(url)
        # Keep watching: if the tunnel drops or the public address stops answering, stop, so start_site.cmd
        # restarts everything with a fresh tunnel (and the fixed link is updated again).
        misses = 0
        while site.poll() is None:
            time.sleep(60)
            if tunnel is not None and tunnel.poll() is not None:
                print("The Cloudflare tunnel stopped; restarting.")
                break
            misses = 0 if public_ok(url) else misses + 1
            if misses >= 3:
                print("The public address stopped answering; restarting with a new tunnel.")
                break
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        for p in (site, tunnel):
            if p is not None and p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
