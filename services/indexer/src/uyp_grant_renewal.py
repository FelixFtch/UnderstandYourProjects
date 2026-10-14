#!/usr/bin/env python3
"""UYP HomeHub grant auto-renewal (2026-10-11, owner-approved).

HomeHub 项目 grant 的 TTL 上限是 24h(设计值)。长跑(索引/稳定性测试)必然
跨天, 到期即 scopes 清空、job 转 offline。本脚本在到期前刷新:
  - 期望清单: /home/jetson/.config/uyp/grants-to-keep.json
    [{"project_id": "...", "source_ids": ["..."], "subject_member_id": "..."}, ...]
  - 若活动 grant 剩余寿命 < RENEW_BEFORE_SECONDS(默认 12h):
      先 revoke(reason=scheduled_renewal) 再 create —— create 对未过期
      grant 会 409, 只能先撤后签; 撤→签之间约 1-2 秒的 scopes 空窗。
  - 全程 journal 留痕(systemd 捕获 stdout); 任何失败下次 timer 再试。
永不触碰其它 grant。幂等: 无到期项时零写入。

2026-10-14 scope 修复(LingoQA 入驻事故): keep 清单只写 "mac-connector",
但查询侧的可见性门禁(projects.visible)要求 sourceScopes 里同时有
connector:<project_id>——缺了它, 索引照跑但项目对所有查询不可见。
现在每个 grant 的 source_ids 一律自动并上 {"mac-connector",
"connector:<project_id>"}(派生, 不靠手写), 且 keep 判定同时检查 TTL
和 source 覆盖——存量窄作用域 grant 会被撤签重建, 不需要人工补刀。
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

HUB = os.environ.get("UYP_HUB_BASE_URL", "http://127.0.0.1:5120")
TOKEN_FILE = os.environ.get("UYP_HOMEHUB_TOKEN_FILE",
                            "/home/jetson/.config/uyp/homehub.token")
KEEP_FILE = os.environ.get("UYP_GRANTS_KEEP_FILE",
                           "/home/jetson/.config/uyp/grants-to-keep.json")
RENEW_BEFORE = int(os.environ.get("UYP_RENEW_BEFORE_SECONDS", "43200"))  # 12h
TTL = int(os.environ.get("UYP_GRANT_TTL_SECONDS", "86400"))  # 24h max


def _req(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        HUB + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def required_sources(project: str, want_sources) -> list[str]:
    """The keep list only names the connector capability; the grant must
    ALSO carry connector:<project> (query-side visibility gate) and
    mac-connector (indexer source gate). Derived, never hand-written."""
    return sorted({"mac-connector", f"connector:{project}",
                   *(str(s) for s in (want_sources or []))})


def main():
    token = open(TOKEN_FILE).read().strip()
    keep = json.load(open(KEEP_FILE))
    now = datetime.now(timezone.utc)
    changed = 0
    for want in keep:
        project = want["project_id"]
        want_sources = required_sources(project, want.get("source_ids"))
        status, grants = _req("GET", "/api/uyp/grants", token)
        active = [g for g in grants.get("grants", [])
                  if g.get("projectId") == project]
        need = True
        if active:
            exp = datetime.fromisoformat(
                active[0]["expiresAt"].replace("Z", "+00:00"))
            have = {str(s) for s in (active[0].get("sourceIds") or [])}
            missing = [s for s in want_sources if s not in have]
            if missing:
                print(f"rescope {project}: 缺 source {missing} -> 撤签重建")
            if exp - now > timedelta(seconds=RENEW_BEFORE) and not missing:
                print(f"keep   {project}: 到期 {active[0]['expiresAt']} 剩余充足")
                need = False
            else:
                gid = active[0]["grantId"]
                s, _ = _req("POST", f"/api/uyp/grants/{gid}/revoke", token,
                            {"reason": "scheduled_renewal"})
                print(f"revoke {project} {gid}: HTTP {s}")
                if s not in (200, 201):
                    continue  # 撤失败就不动, 下轮再试
        if need:
            s, body = _req("POST", "/api/uyp/grants", token, {
                "project_id": project,
                "source_ids": want_sources,
                "subject_member_id": want["subject_member_id"],
                "ttl_seconds": TTL,
            })
            print(f"create {project}: HTTP {s} sources={want_sources} "
                  f"{body.get('grant', {}).get('expiresAt', body)}")
            if s in (200, 201):
                changed += 1
    print(f"renewal pass done: {changed} re-issued")
    # 顺带刷新 run-pending 用的 access-context 文件(过期会让增量静默跳过)
    ctx_file = os.environ.get("UYP_ACCESS_CONTEXT_FILE",
                              "/home/jetson/.config/uyp/access-context.json")
    try:
        s2, body = _req("GET", "/api/uyp/access-context", token)
        if s2 == 200 and body.get("accessContext"):
            with open(ctx_file, "w") as fh:
                json.dump(body["accessContext"], fh, indent=1)
            print(f"context refreshed -> {ctx_file} "
                  f"(expires {body['accessContext'].get('expiresAt')})")
        else:
            print(f"context refresh skipped: HTTP {s2}")
    except OSError as exc:
        print(f"context refresh failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
