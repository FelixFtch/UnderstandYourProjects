#!/usr/bin/env python3
"""Jetson-side client for the Jarvis Connector (CONNECTOR_PROTOCOL_V1).

Usage: connector_client.py --host http://<mac>:7121 --token-file ~/.config/uyp/token
Subcommands: grants | manifest [--limit N] | read <relpath> [--length N]
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request

def api(host, token, path, binary=False):
    req = urllib.request.Request(host.rstrip("/") + path,
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        return data if binary else json.loads(data)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--token-file", default=os.path.expanduser("~/.config/uyp/token"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("grants")
    m = sub.add_parser("manifest"); m.add_argument("--grant", required=True); m.add_argument("--limit", type=int, default=20)
    r = sub.add_parser("read"); r.add_argument("--grant", required=True); r.add_argument("relpath"); r.add_argument("--length", type=int, default=512)
    a = ap.parse_args()
    token = open(os.path.expanduser(a.token_file)).read().strip()
    if a.cmd == "grants":
        print(json.dumps(api(a.host, token, "/grants"), ensure_ascii=False, indent=1))
    elif a.cmd == "manifest":
        d = api(a.host, token, f"/manifest?grant={a.grant}")
        print(f"grant={d['grant']} root={d['root_name']} total={d['total']} has_more={d['has_more']}")
        for f in d["files"][:a.limit]:
            print(f"  {f['kind']:6s} {f['size']:>9} {f['relpath']}")
    elif a.cmd == "read":
        d = api(a.host, token, f"/read?grant={a.grant}&relpath={a.relpath}&length={a.length}", binary=True)
        sys.stdout.write(d.decode("utf-8", errors="replace"))

if __name__ == "__main__":
    main()
