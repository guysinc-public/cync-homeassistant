#!/usr/bin/env python3
"""Cync cloud probe. Run: docker exec -it homeassistant python3 /config/cync_probe.py"""
import asyncio, getpass, json, os, random, string, sys, time
import aiohttp

BASE = "https://api.gelighting.com"
CORP = "1007d2ad150c4000"
STATE = "/config/cync_probe_state.json"
REDACT = {"access_token", "refresh_token", "authorize", "authorize_code",
          "access_key", "mac", "wifiMac", "email", "password"}
SHOW = ("id", "name", "source", "product_id", "is_online", "firmware_version",
        "role", "is_owner", "owner", "share", "shared", "user_id")


def redact(o):
    if isinstance(o, dict):
        return {k: ("<redacted>" if k in REDACT else redact(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [redact(x) for x in o]
    return o


async def call(s, method, path, *, token=None, body=None):
    headers = {"Access-Token": token} if token else {}
    data = json.dumps(body) if body is not None else None
    async with s.request(method, BASE + path, headers=headers, data=data) as r:
        text = await r.text()
        try:
            js = json.loads(text)
        except ValueError:
            js = text
        print(f"{method} {path} -> {r.status}")
        return r.status, js


async def main():
    email = input("Cync email: ").strip()
    pw = getpass.getpass("Password: ")
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    resource = st.get("resource") or "".join(random.choices(string.ascii_lowercase, k=16))
    print("resource:", resource, "(reused)" if st.get("resource") else "(new)")

    async with aiohttp.ClientSession() as s:
        # Q1: does a plain password login with a resource succeed, or demand 2FA?
        code, js = await call(s, "POST", "/v2/user_auth",
                              body={"corp_id": CORP, "email": email, "password": pw, "resource": resource})
        print("  body:", redact(js))
        if code != 200:
            await call(s, "POST", "/v2/two_factor/email/verifycode",
                       body={"corp_id": CORP, "email": email, "local_lang": "en-us"})
            otp = input("2FA code from email (check spam): ").strip()
            code, js = await call(s, "POST", "/v2/user_auth/two_factor",
                                  body={"corp_id": CORP, "email": email, "password": pw[:16],
                                        "two_factor": otp, "resource": resource})
            print("  body:", redact(js))
            if code != 200:
                sys.exit("login failed")
        tok, ref, uid = js["access_token"], js["refresh_token"], js["user_id"]
        print("  expire_in:", js.get("expire_in"), "seconds")
        json.dump({"resource": resource, "user_id": uid, "access_token": tok,
                   "refresh_token": ref, "t": time.time()}, open(STATE, "w"))
        os.chmod(STATE, 0o600)

        # Q2: how does the shared home appear in subscribe/devices?
        code, devs = await call(s, "GET", f"/v2/user/{uid}/subscribe/devices", token=tok)
        if not isinstance(devs, list):
            sys.exit(f"unexpected device list: {redact(devs)}")
        for d in devs:
            print("  entry:", {k: d.get(k) for k in SHOW if k in d})
            extra = sorted(set(d) - set(SHOW) - REDACT - {"is_active"})
            if extra:
                print("    other keys:", extra)
        # Q3: does the property endpoint answer for every entry with a product_id?
        for d in devs:
            if d.get("product_id"):
                code, prop = await call(s, "GET",
                                        f"/v2/product/{d['product_id']}/device/{d['id']}/property", token=tok)
                if isinstance(prop, dict):
                    print(f"    {d.get('name')!r}: bulbsArray={len(prop.get('bulbsArray', []))} "
                          f"groupsArray={len(prop.get('groupsArray', []))} keys={sorted(prop)[:12]}")
                else:
                    print("    ", prop)

        # Q4: does refresh work, does it rotate, is the old token single-use?
        code, js = await call(s, "POST", "/v2/user/token/refresh", body={"refresh_token": ref})
        print("  body:", redact(js))
        if code == 200:
            print("  rotated:", js.get("refresh_token") != ref, "expire_in:", js.get("expire_in"))
            code2, _ = await call(s, "POST", "/v2/user/token/refresh", body={"refresh_token": ref})
            print("  old refresh token reusable:", code2 == 200)
            tok, ref = js["access_token"], js.get("refresh_token", ref)
        else:
            code, js = await call(s, "POST", "/v2/user/token/refresh", token=tok,
                                  body={"refresh_token": ref, "corp_id": CORP})
            print("  retry with Access-Token + corp_id:", code, redact(js))

        # Q5: does the same resource skip 2FA on the next password login?
        code, js = await call(s, "POST", "/v2/user_auth",
                              body={"corp_id": CORP, "email": email, "password": pw, "resource": resource})
        print("  same-resource re-login skips 2FA:", code == 200, "" if code == 200 else redact(js))
        code, _ = await call(s, "GET", f"/v2/user/{uid}/subscribe/devices", token=tok)
        print("  first session still valid after re-login:", code == 200)

        # Q6: does opening the phone app kill this session?
        input("Open the Cync app on your phone, browse the shared home, wait 30 s, then press Enter...")
        code, _ = await call(s, "GET", f"/v2/user/{uid}/subscribe/devices", token=tok)
        print("  session still valid after phone app use:", code == 200)


asyncio.run(main())
