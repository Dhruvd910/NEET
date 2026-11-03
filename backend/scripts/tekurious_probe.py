"""One-off check of the Tekurious AI-Auth API with your own phone, to see its real responses.

    python scripts/tekurious_probe.py

Sends one SMS code to the phone you type, asks for the code, and prints the *shape* of each response.
Token values are hidden; nothing is saved.
"""
import os
import sys
from pathlib import Path

import httpx

BASE = "https://api.tekurious.si"


def key() -> str:
    for line in (Path(__file__).resolve().parent.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("TEKURIOUS_API_KEY="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("TEKURIOUS_API_KEY", "")


def mask(value):
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value[:3]]
    if isinstance(value, str) and len(value) > 24:
        return value[:6] + "…(hidden)"
    return value


def show(label: str, r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError:
        body = r.text[:300]
    print(f"\n{label}: HTTP {r.status_code}\n  {mask(body)}")
    return body if isinstance(body, dict) else {}


def main() -> None:
    h = {"x-api-key": key()}
    if not h["x-api-key"]:
        sys.exit("TEKURIOUS_API_KEY is missing from backend/.env")
    phone = input("Your phone in international format (e.g. +919876543210): ").strip().replace(" ", "")
    sent = show("otp/send", httpx.post(f"{BASE}/v1/otp/send", headers=h, json={"phone": phone}, timeout=30))
    code = input("\nCode from the SMS: ").strip()
    # Confirmed by testing (the PDF says phone + code): verify takes the send step's reqId and the code as "otp".
    body = {"reqId": sent.get("reqId"), "otp": code}
    print(f"(verify request fields: {sorted(body)})")
    session = show("otp/verify", httpx.post(f"{BASE}/v1/otp/verify", headers=h, json=body, timeout=30))
    token = session.get("accessToken") or session.get("access_token") or (session.get("tokens") or {}).get("accessToken")
    if not token:
        print("\nNo access token in the reply; send the output above to Claude.")
        return
    auth = {**h, "Authorization": f"Bearer {token}"}
    show("me", httpx.get(f"{BASE}/v1/me", headers=auth, timeout=30))
    show("me/capabilities", httpx.get(f"{BASE}/v1/me/capabilities", headers=auth, timeout=30))
    show("self-signup (empty body: shows required fields only)",
         httpx.post(f"{BASE}/v1/self-signup", headers=auth, json={}, timeout=30))
    print("\nDone. Copy everything above (tokens are hidden) and send it to Claude.")


if __name__ == "__main__":
    main()
