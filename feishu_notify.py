# -*- coding: utf-8 -*-
"""飞书通知模块（v4.6 · 数据采样与训练痕迹推送）

事件 → 消息：
- 病例反馈（采纳 / 修正）→ notify_feedback
- 拍照分析匿名计数        → notify_photo
- AI 问答留痕             → notify_chat
- 联邦训练痕迹            → notify_train

原则：
- 凭证不在本项目落盘：运行时从 OpenClaw 配置读取
  （openclaw.json → channels.feishu.accounts.main 的 appId / appSecret）
- 后台线程异步发送；任何异常只写日志，绝不影响主流程
- 消息按「登录医院视角」描述；联邦中心账号 = 全局视角

配置：data/feishu_notify.json（不含任何密钥）
日志：stdout（随主进程控制台输出，v4.9.3 起不落盘）
"""
import json
import os
import threading
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
_CFG_FILE = os.path.join(BASE, "data", "feishu_notify.json")
# v4.9.3：日志输出到 stdout，不写文件（便于移植 / 打包）

_DEFAULT_CFG = {
    "enabled": True,
    "chat_id": "oc_00000000000000000000000000000000",
    # 飞书应用凭证的读取位置（可选）。默认从环境变量 HG_FEISHU_CONFIG 读取；
    # 不配置时飞书推送静默跳过，不影响任何主流程。
    "openclaw_config": os.environ.get("HG_FEISHU_CONFIG", ""),
    "events": {"feedback": True, "photo": True, "chat": True, "train": True},
}

_tok = {"v": None, "exp": 0.0}
_lock = threading.Lock()


def _log(line):
    """v4.9.3：输出到 stdout（后台线程打印，不影响主流程）"""
    try:
        print("%s [feishu] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), line), flush=True)
    except Exception:
        pass


def _cfg():
    """读取配置（每次实时读取，改动立即生效）"""
    c = dict(_DEFAULT_CFG)
    try:
        if os.path.exists(_CFG_FILE):
            with open(_CFG_FILE, encoding="utf-8") as f:
                loaded = json.load(f) or {}
            ev = dict(_DEFAULT_CFG["events"])
            if isinstance(loaded.get("events"), dict):
                ev.update({k: bool(v) for k, v in loaded["events"].items()})
            c.update(loaded)
            c["events"] = ev
    except Exception as e:
        _log("[cfg] 配置读取失败：%s" % e)
    return c


def _event_on(name):
    return bool((_cfg().get("events") or {}).get(name, True))


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _who(acc):
    if not acc:
        return "未知账号"
    if acc.get("center"):
        return "联邦中心（全局视角）"
    return "%s（%s 院）" % (acc.get("name") or "医院", acc.get("hospital") or "?")


def _model_info():
    """读取当前全局模型快照（用于数据采样消息中的「训练痕迹」行）"""
    try:
        p = os.path.join(BASE, "data", "fed_model.json")
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        if m.get("version"):
            return "v%s · 损失 %s · 留出集 %s%%" % (
                m.get("version"), m.get("loss"), m.get("holdout_acc"))
    except Exception:
        pass
    return None


def _token():
    now = time.time()
    with _lock:
        if _tok["v"] and now < _tok["exp"] - 300:
            return _tok["v"]
    path = _cfg().get("openclaw_config") or _DEFAULT_CFG["openclaw_config"]
    if not path or not os.path.exists(path):
        raise RuntimeError("未配置 HG_FEISHU_CONFIG（飞书应用凭证），跳过推送")
    with open(path, encoding="utf-8") as f:
        conf = json.load(f)
    accs = ((conf.get("channels") or {}).get("feishu") or {}).get("accounts") or {}
    main = accs.get("main") or (next(iter(accs.values())) if accs else {})
    app_id = main.get("appId")
    app_secret = main.get("appSecret")
    if not app_id or not app_secret:
        raise RuntimeError("openclaw.json 中未找到飞书应用凭证")
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    if d.get("code") != 0:
        raise RuntimeError("tenant_access_token 获取失败：%s %s" % (d.get("code"), d.get("msg")))
    with _lock:
        _tok["v"] = d["tenant_access_token"]
        _tok["exp"] = now + int(d.get("expire", 7200))
    return _tok["v"]


def _send(text):
    """同步发送（供后台线程 / 自检调用）；返回飞书响应 dict 或 None"""
    cfg = _cfg()
    if not cfg.get("enabled"):
        return None
    try:
        tok = _token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        body = {"receive_id": cfg.get("chat_id"), "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False)}
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8",
                     "Authorization": "Bearer " + tok})
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        if d.get("code") == 0:
            _log("[ok] 已发送 message_id=%s" % ((d.get("data") or {}).get("message_id")))
        else:
            _log("[fail] code=%s msg=%s" % (d.get("code"), d.get("msg")))
        return d
    except Exception as e:
        _log("[err] 发送失败：%s" % e)
        return None


def _push(text):
    """异步推送入口：绝不抛出"""
    try:
        if not _cfg().get("enabled"):
            return
        threading.Thread(target=_send, args=(text,), daemon=True).start()
    except Exception as e:
        _log("[push-err] %s" % e)


def notify_feedback(acc, item, stored):
    try:
        if not _event_on("feedback"):
            return
        act = "采纳" if (item or {}).get("action") == "adopt" else "修正"
        syms = " / ".join((item or {}).get("symptoms") or []) or "—"
        lines = [
            "【联邦医院知识图谱AI · 数据采样】",
            "医院：%s" % _who(acc),
            "事件：病例反馈 · %s（+1）" % act,
            "内容：%s → %s" % (syms, (item or {}).get("disease") or "?"),
            "本院样本池：%d 条 · 待并入下轮训练" % stored,
            "训练痕迹：本地沉淀（数据不出院），下次「再训一轮」自动并入",
        ]
        mi = _model_info()
        if mi:
            lines.append("当前全局模型：%s" % mi)
        lines.append("时间：%s" % _now())
        _push("\n".join(lines))
    except Exception as e:
        _log("[feedback-err] %s" % e)


def notify_photo(acc, rules, total):
    try:
        if not _event_on("photo"):
            return
        mapped = (rules or {}).get("mapped") or {}
        wound = mapped.get("wound") or "未分类"
        insects = "、".join(mapped.get("insects") or []) or "—"
        level = (rules or {}).get("level") or "—"
        if (acc or {}).get("center"):
            ev = "事件：拍照分析（中心视角 · 不产生本院计数）"
            stat_line = "说明：照片不出院；中心账号不产生区域统计"
        else:
            ev = "事件：拍照分析 · 匿名计入统计（+1）"
            stat_line = "本院统计：累计 %d 条（照片不出院，仅类别计数）" % total
        text = ("【联邦医院知识图谱AI · 数据采样】\n"
                "医院：%s\n"
                "%s\n"
                "内容：%s · 昆虫：%s · 建议级别：%s\n"
                "%s\n"
                "时间：%s" % (_who(acc), ev, wound, insects, level, stat_line, _now()))
        _push(text)
    except Exception as e:
        _log("[photo-err] %s" % e)


def notify_chat(acc, question, hit):
    try:
        if not _event_on("chat"):
            return
        q = (question or "").strip().replace("\n", " ")
        if len(q) > 40:
            q = q[:40] + "…"
        text = ("【联邦医院知识图谱AI · 数据采样】\n"
                "医院：%s\n"
                "事件：AI 问答（知识库%s）\n"
                "提问：%s\n"
                "说明：问答仅作运行留痕，不构成训练样本\n"
                "时间：%s" % (_who(acc), "命中" if hit else "未命中", q or "（空）", _now()))
        _push(text)
    except Exception as e:
        _log("[chat-err] %s" % e)


def notify_train(acc, result, model):
    try:
        if not _event_on("train"):
            return
        result = result or {}
        hist = result.get("history") or [{}]
        fin = result.get("final") or {}
        hold = result.get("holdout") or {}
        fb = result.get("feedback_counts") or {}
        since = result.get("feedback_since") or {}
        if (acc or {}).get("center"):
            pool = ("样本：%s 条（合成 %s + 反馈并入 %s）· 本轮新增反馈 %s 条" % (
                result.get("total_samples"), result.get("synthetic_samples"),
                sum(fb.values()), sum(int(v or 0) for v in since.values())))
            if fb:
                pool += "\n各院反馈并入：" + " / ".join(
                    "%s %s" % (h, fb.get(h, 0)) for h in ("A", "B", "C", "D", "E", "F"))
        else:
            hid = (acc or {}).get("hospital")
            pool = ("样本：%s 条 · 本院反馈并入 %s 条 · 本轮新增 %s 条" % (
                result.get("total_samples"), fb.get(hid, 0), since.get(hid, 0)))
        text = ("【联邦医院知识图谱AI · 训练痕迹】\n"
                "发起：%s\n"
                "轮次：%s 轮 · 模型 v%s\n"
                "损失：%s → %s ｜ 准确率：%s%%\n"
                "留出集：%s%%（n=%s）\n"
                "%s\n"
                "说明：全局模型已下发到各院诊断引擎（仅聚合参数，数据不出院）\n"
                "时间：%s" % (_who(acc), result.get("rounds"), (model or {}).get("version"),
                              hist[0].get("loss"), fin.get("loss"), fin.get("acc"),
                              hold.get("acc"), hold.get("n"), pool, _now()))
        _push(text)
    except Exception as e:
        _log("[train-err] %s" % e)


def self_test():
    """自检：同步发送一条通道测试消息（返回响应或 None）"""
    return _send("【联邦医院知识图谱AI · 通道测试】\n"
                 "飞书通知通道已连通，后续数据采样与训练痕迹将推送到这里。\n"
                 "时间：%s" % _now())


if __name__ == "__main__":
    r = self_test()
    if r and r.get("code") == 0:
        print("OK message_id:", (r.get("data") or {}).get("message_id"))
    else:
        print("NOT SENT / FAILED ->", json.dumps(r, ensure_ascii=False) if r else "see stdout")
