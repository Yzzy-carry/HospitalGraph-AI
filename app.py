# -*- coding: utf-8 -*-
"""
联邦医院知识图谱AI — Flask + MySQL 后端
访问: http://localhost:5000
"""

from flask import Flask, render_template_string, request, jsonify, make_response
import pymysql
import random
import os

app = Flask(__name__)

DB = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "hospital_graph",
    "charset": "utf8",
    "cursorclass": pymysql.cursors.DictCursor,
}

# ── CORS 全局处理 ──

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ── 数据库工具函数 ──

def q(sql, *args):
    """执行查询并返回所有行"""
    db = pymysql.connect(**DB)
    cur = db.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    db.close()
    return rows


def ex(sql, *args):
    """执行写操作"""
    db = pymysql.connect(**DB)
    cur = db.cursor()
    cur.execute(sql, args)
    db.commit()
    db.close()


# ── 首页 ──

@app.route("/")
def index():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(html_path, encoding="utf-8") as f:
        return render_template_string(f.read())


# ── API: 医院列表 ──

@app.route("/api/hospitals")
def api_hospitals():
    return jsonify(q("SELECT * FROM hospitals"))


# ── API: 疾病列表（含关联症状/药物/检查/预防/发病率）──

@app.route("/api/diseases")
def api_diseases():
    rows = q("SELECT * FROM diseases")
    for r in rows:
        r["symptoms"] = [
            x["name"]
            for x in q(
                "SELECT s.name FROM symptoms s "
                "JOIN disease_symptoms ds ON s.id = ds.symptom_id "
                "WHERE ds.disease_id = %s",
                r["id"],
            )
        ]
        r["drugs"] = [
            x["name"]
            for x in q(
                "SELECT d.name FROM drugs d "
                "JOIN disease_drugs dd ON d.id = dd.drug_id "
                "WHERE dd.disease_id = %s",
                r["id"],
            )
        ]
        r["tests"] = [
            x["name"]
            for x in q(
                "SELECT t.name FROM tests t "
                "JOIN disease_tests dt ON t.id = dt.test_id "
                "WHERE dt.disease_id = %s",
                r["id"],
            )
        ]
        r["preventions"] = [
            x["content"]
            for x in q(
                "SELECT content FROM preventions WHERE disease_id = %s",
                r["id"],
            )
        ]
        r["rates"] = {
            x["hospital_id"]: float(x["rate"])
            for x in q(
                "SELECT hospital_id, rate FROM prevalence_rates WHERE disease_id = %s",
                r["id"],
            )
        }
    return jsonify(rows)


# ── API: 所有症状名 ──

@app.route("/api/symptoms")
def api_symptoms():
    return jsonify([r["name"] for r in q("SELECT name FROM symptoms ORDER BY name")])


# ── API: 症状推理诊断（三因素加权）──

@app.route("/api/diagnose", methods=["POST"])
def api_diagnose():
    data = request.get_json()
    symptoms = data.get("symptoms", [])
    hospital_id = data.get("hospital_id", "A")
    if not symptoms:
        return jsonify([])

    diseases = q("SELECT * FROM diseases")
    results = []
    for d in diseases:
        ds_symptoms = [
            x["name"]
            for x in q(
                "SELECT s.name FROM symptoms s "
                "JOIN disease_symptoms ds ON s.id = ds.symptom_id "
                "WHERE ds.disease_id = %s",
                d["id"],
            )
        ]
        matched = sum(1 for s in symptoms if s in ds_symptoms)
        if matched == 0:
            continue

        # 症状匹配度 (60%)
        sm_score = matched / max(len(ds_symptoms), 1)

        # 本地发病率 (20%)
        rate_row = q(
            "SELECT rate FROM prevalence_rates WHERE disease_id = %s AND hospital_id = %s",
            d["id"],
            hospital_id,
        )
        avg_rate = float(rate_row[0]["rate"]) if rate_row else 0.05
        br_score = min(avg_rate * 5, 1)

        # 严重度 (20%)
        sv_map = {"危急": 1.0, "严重": 0.7, "中度": 0.5, "轻度": 0.3}
        sv_score = sv_map.get(d["severity"], 0.5)

        score = round((sm_score * 0.6 + br_score * 0.2 + sv_score * 0.2) * 100)
        if score > 3:
            drugs = [
                x["name"]
                for x in q(
                    "SELECT d.name FROM drugs d "
                    "JOIN disease_drugs dd ON d.id = dd.drug_id "
                    "WHERE dd.disease_id = %s",
                    d["id"],
                )
            ]
            tests = [
                x["name"]
                for x in q(
                    "SELECT t.name FROM tests t "
                    "JOIN disease_tests dt ON t.id = dt.test_id "
                    "WHERE dt.disease_id = %s",
                    d["id"],
                )
            ]
            prevs = [
                x["content"]
                for x in q(
                    "SELECT content FROM preventions WHERE disease_id = %s LIMIT 4",
                    d["id"],
                )
            ]
            results.append(
                {
                    "disease": d["name"],
                    "icon": d["icon"],
                    "dept": d["dept"],
                    "severity": d["severity"],
                    "score": score,
                    "matched": matched,
                    "total": len(ds_symptoms),
                    "drugs": drugs,
                    "tests": tests,
                    "prevention": prevs,
                    "cause": d["cause"],
                    "urgent": d["severity"] in ("危急", "严重"),
                }
            )

    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(results[:6])


# ── API: 知识图谱（节点 + 边）──

@app.route("/api/graph")
def api_graph():
    hospital_id = request.args.get("hospital", "A")
    nodes, edges, nm, nid = [], [], {}, 0

    def add_node(label, ntype):
        nonlocal nid
        if label in nm:
            return nm[label]
        nm[label] = nid
        nodes.append({"id": nid, "label": label, "type": ntype})
        nid += 1
        return nid - 1

    diseases = q("SELECT * FROM diseases")
    for d in diseases:
        did = add_node(d["name"], "disease")
        add_node(d["dept"], "dept")
        edges.append({"source": did, "target": nm[d["dept"]]})

        for s in q(
            "SELECT s.name FROM symptoms s "
            "JOIN disease_symptoms ds ON s.id = ds.symptom_id "
            "WHERE ds.disease_id = %s",
            d["id"],
        ):
            edges.append({"source": did, "target": add_node(s["name"], "symptom")})

        for dr in q(
            "SELECT d.name FROM drugs d "
            "JOIN disease_drugs dd ON d.id = dd.drug_id "
            "WHERE dd.disease_id = %s",
            d["id"],
        ):
            edges.append({"source": did, "target": add_node(dr["name"], "drug")})

        for t in q(
            "SELECT t.name FROM tests t "
            "JOIN disease_tests dt ON t.id = dt.test_id "
            "WHERE dt.disease_id = %s",
            d["id"],
        ):
            edges.append({"source": did, "target": add_node(t["name"], "test")})

    return jsonify({"nodes": nodes, "edges": edges})


# ── 模拟病例数据（固定种子）──

# 中国人常见姓氏 & 名字用字
_SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
    "徐", "孙", "马", "胡", "朱", "郭", "何", "罗", "高", "林",
]
_GIVEN_MALE = [
    "伟", "强", "磊", "洋", "勇", "军", "杰", "涛", "明", "辉",
    "鹏", "浩", "宇", "飞", "华", "超", "鑫", "志", "国", "文",
]
_GIVEN_FEMALE = [
    "芳", "敏", "静", "丽", "婷", "娟", "霞", "雪", "玲", "艳",
    "慧", "秀", "云", "燕", "萍", "珊", "颖", "莉", "怡", "琳",
]
_GENDER = ["男", "女"]
_OUTCOMES = ["治愈", "好转", "未愈", "死亡", "转院", "出院", "稳定"]


def _generate_cases(hospital_id):
    """为指定医院生成模拟病例（固定种子，每次请求结果不变）"""
    # 用医院 ID 的 hash 作为种子
    seed = sum(ord(c) for c in hospital_id) * 113 + len(hospital_id) * 7
    rng = random.Random(seed)

    diseases = q("SELECT * FROM diseases")
    if not diseases:
        return []

    # 固定病例数（用种子派生）
    case_count = rng.randint(120, 200)

    cases = []
    for i in range(case_count):
        # 姓氏
        surname = rng.choice(_SURNAMES)
        # 性别
        gender = rng.choice(_GENDER)
        # 名字
        given_pool = _GIVEN_MALE if gender == "男" else _GIVEN_FEMALE
        given = rng.choice(given_pool) + rng.choice(given_pool)
        name = surname + given
        # 年龄
        age = rng.randint(1, 90)
        # 疾病（权重：发病率高的更容易出现）
        disease = rng.choice(diseases)
        # 严重度
        severities = ["轻度", "中度", "严重", "危急"]
        sev_weights = [0.35, 0.35, 0.20, 0.10]
        severity = rng.choices(severities, weights=sev_weights, k=1)[0]
        # 住院天数
        if severity == "轻度":
            hospital_days = rng.randint(1, 5)
        elif severity == "中度":
            hospital_days = rng.randint(3, 14)
        elif severity == "严重":
            hospital_days = rng.randint(7, 30)
        else:
            hospital_days = rng.randint(10, 60)
        # 转归
        if severity == "危急":
            outcome = rng.choices(
                ["治愈", "好转", "未愈", "死亡"],
                weights=[0.2, 0.3, 0.2, 0.3],
                k=1,
            )[0]
        elif severity == "严重":
            outcome = rng.choices(
                ["治愈", "好转", "未愈", "死亡", "转院"],
                weights=[0.3, 0.4, 0.1, 0.05, 0.15],
                k=1,
            )[0]
        elif severity == "中度":
            outcome = rng.choices(
                ["治愈", "好转", "未愈", "转院"],
                weights=[0.5, 0.3, 0.1, 0.1],
                k=1,
            )[0]
        else:
            outcome = rng.choices(
                ["治愈", "出院", "好转"],
                weights=[0.6, 0.3, 0.1],
                k=1,
            )[0]

        cases.append(
            {
                "id": i + 1,
                "name": name,
                "age": age,
                "gender": gender,
                "disease": disease["name"],
                "severity": severity,
                "hospital_days": hospital_days,
                "outcome": outcome,
            }
        )
    return cases


@app.route("/api/cases")
def api_cases():
    hospital_id = request.args.get("hospital", "A")
    cases = _generate_cases(hospital_id)
    return jsonify(cases)


# ── API: 医院统计 ──

@app.route("/api/stats")
def api_stats():
    hospital_id = request.args.get("hospital", "A")
    cases = _generate_cases(hospital_id)

    total = len(cases)
    if total == 0:
        return jsonify(
            {
                "total_cases": 0,
                "disease_count": 0,
                "critical_count": 0,
                "avg_hospital_days": 0,
                "hospital_id": hospital_id,
            }
        )

    diseases_set = set()
    critical_count = 0
    total_days = 0

    for c in cases:
        diseases_set.add(c["disease"])
        if c["severity"] in ("危急",):
            critical_count += 1
        total_days += c["hospital_days"]

    return jsonify(
        {
            "total_cases": total,
            "disease_count": len(diseases_set),
            "critical_count": critical_count,
            "avg_hospital_days": round(total_days / total, 1),
            "hospital_id": hospital_id,
        }
    )


# ── API: 所有医院概览 ──

@app.route("/api/overview")
def api_overview():
    hospitals = q("SELECT * FROM hospitals")
    results = []
    for h in hospitals:
        hospital_id = h["id"]
        cases = _generate_cases(hospital_id)
        total = len(cases)
        diseases_set = set()
        critical_count = 0
        total_days = 0
        for c in cases:
            diseases_set.add(c["disease"])
            if c["severity"] in ("危急",):
                critical_count += 1
            total_days += c["hospital_days"]

        results.append(
            {
                "hospital_id": hospital_id,
                "hospital_name": h.get("name", hospital_id),
                "total_cases": total,
                "disease_count": len(diseases_set),
                "critical_count": critical_count,
                "avg_hospital_days": round(total_days / total, 1) if total > 0 else 0,
                "critical_rate": round(critical_count / total * 100, 1) if total > 0 else 0,
            }
        )
    return jsonify(results)


# ============================================================
# 账号与会话（后端升级 v1 · 7 医院演示账号）
# ============================================================
import uuid as _uuid
import time as _time

_ACCOUNTS = {
    "zhongxin": {"pw": "demo2026", "hospital": "A", "name": "中心医院", "role": "hospital", "center": False},
    "diyi":     {"pw": "demo2026", "hospital": "B", "name": "市第一人民医院", "role": "hospital", "center": False},
    "fusan":    {"pw": "demo2026", "hospital": "C", "name": "附属第三医院", "role": "hospital", "center": False},
    "sheng2":   {"pw": "demo2026", "hospital": "D", "name": "省第二人民医院", "role": "hospital", "center": False},
    "fuyou":    {"pw": "demo2026", "hospital": "E", "name": "妇幼保健院", "role": "hospital", "center": False},
    "kaifa":    {"pw": "demo2026", "hospital": "F", "name": "开发区医院", "role": "hospital", "center": False},
    "fcenter":  {"pw": "demo2026", "hospital": "ALL", "name": "联邦中心", "role": "admin", "center": True},
}

_SESSIONS = {}  # token -> 会话信息


@app.route("/api/login", methods=["POST", "OPTIONS"])
def api_login():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    acc = _ACCOUNTS.get(username)
    if not acc or password != acc["pw"]:
        return jsonify({"ok": False, "error": "账号或密码错误"}), 401
    token = _uuid.uuid4().hex
    _SESSIONS[token] = {"username": username, "ts": _time.time()}
    return jsonify({
        "ok": True, "token": token,
        "user": {"username": username, "hospital": acc["hospital"], "name": acc["name"],
                 "role": acc["role"], "center": acc["center"]},
    })


@app.route("/api/logout", methods=["POST", "OPTIONS"])
def api_logout():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    _SESSIONS.pop((data.get("token") or ""), None)
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    token = request.headers.get("X-Token") or request.args.get("token") or ""
    sess = _SESSIONS.get(token)
    if not sess:
        return jsonify({"ok": False, "error": "未登录或会话已失效"}), 401
    if _time.time() - sess["ts"] > 24 * 3600:
        _SESSIONS.pop(token, None)
        return jsonify({"ok": False, "error": "会话已过期"}), 401
    acc = _ACCOUNTS.get(sess["username"], {})
    return jsonify({
        "ok": True,
        "user": {"username": sess["username"], "hospital": acc.get("hospital"), "name": acc.get("name"),
                 "role": acc.get("role"), "center": acc.get("center")},
    })


# ── 新版设计页（v4：登录已接入后台鉴权，离线时自动回退本地校验）──

@app.route("/v4")
def v4_page():
    p4 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v4.html")
    with open(p4, encoding="utf-8") as f4:
        return f4.read()


@app.route("/legacy")
def legacy_page():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index_legacy.html")
    with open(p, encoding="utf-8") as f:
        return f.read()


# ============================================================
# 联邦学习接口（演示级 FedAvg · 合成模拟数据）
# ============================================================
_FL_CACHE = {}


def _fl_run(rounds=15):
    import numpy as _np
    rng = _np.random.RandomState(42)
    specs = [
        ("A", "中心医院", 120, 1.15, 1.00),
        ("B", "市第一人民医院", 90, 1.45, 1.05),
        ("C", "附属第三医院", 150, 0.95, 0.98),
        ("D", "省第二人民医院", 60, 1.70, 1.10),
        ("E", "妇幼保健院", 120, 1.05, 0.95),
        ("F", "开发区医院", 60, 1.55, 1.02),
    ]
    data = []
    for hid, name, n, slope, base in specs:
        x = rng.randn(n, 1) * 0.4 + base
        y = slope * x + rng.randn(n, 1) * 0.15
        data.append((hid, name, n, x, y))
    ax = _np.vstack([d[3] for d in data])
    ay = _np.vstack([d[4] for d in data])

    def mse(w):
        return float(_np.mean((ax * w - ay) ** 2))

    def local_train(w, x, y, steps=2, lr=0.05):
        n = len(x)
        for _ in range(steps):
            grad = (2.0 / n) * x.T @ (x * w - y)
            w = w - lr * grad
        return w

    w = _np.zeros((1, 1))
    history = [{"r": 0, "w": 0.0, "loss": round(mse(w), 4)}]
    for r in range(1, rounds + 1):
        ws, ns = [], []
        for hid, name, n, x, y in data:
            ws.append(local_train(w.copy(), x, y))
            ns.append(n)
        total = sum(ns)
        w = sum(wl * (nn / total) for wl, nn in zip(ws, ns))
        history.append({"r": r, "w": round(float(w.item()), 4), "loss": round(mse(w), 4)})
    solo = []
    for hid, name, n, x, y in data:
        ws = local_train(_np.zeros((1, 1)), x, y, steps=400)
        solo.append({"id": hid, "name": name, "n": n, "w": round(float(ws.item()), 3), "loss": round(mse(ws), 3)})
    return {
        "ok": True, "rounds": rounds, "total_samples": int(sum(d[2] for d in data)),
        "history": history, "solo": solo, "final": history[-1],
        "note": "演示级 FedAvg · 合成模拟数据（非真实患者数据）",
    }


@app.route("/api/fl/train")
def api_fl_train():
    rounds = request.args.get("rounds", 15, type=int)
    rounds = max(1, min(30, rounds))
    if rounds not in _FL_CACHE:
        _FL_CACHE[rounds] = _fl_run(rounds)
    return jsonify(_FL_CACHE[rounds])




# ── 启动 ──


# ============================================================
# AI 聊天接口（百炼大模型 + MySQL 知识库 RAG）
# ============================================================
import requests as _requests

BAILIAN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
BAILIAN_API_KEY = os.environ.get("BAILIAN_KEY", "")
BAILIAN_MODEL = "qwen-plus"

# 全部症状词表（用于从用户问题里匹配疾病知识）
_ALL_SYMPTOMS = []
def _all_symptoms():
    global _ALL_SYMPTOMS
    if not _ALL_SYMPTOMS:
        _ALL_SYMPTOMS = [r["name"] for r in q("SELECT name FROM symptoms")]
    return _ALL_SYMPTOMS

def _retrieve_knowledge(question):
    """RAG检索：从问题中匹配症状关键词，查出相关疾病知识"""
    matched = [s for s in _all_symptoms() if s in question]
    if not matched:
        # 再试试疾病名直接匹配
        diseases = q("SELECT name, severity, cause FROM diseases")
        hits = [d for d in diseases if d["name"] in question]
        if not hits:
            return ""
        knowledge = ""
        for d in hits:
            knowledge += "疾病【%s】严重度%s：%s\n" % (d["name"], d["severity"], (d["cause"] or "")[:100])
        return knowledge

    knowledge = ""
    seen = set()
    for s in matched:
        rows = q("""SELECT DISTINCT d.id, d.name, d.severity, d.cause
                    FROM diseases d
                    JOIN disease_symptoms ds ON d.id=ds.disease_id
                    JOIN symptoms s ON s.id=ds.symptom_id
                    WHERE s.name=%s""", (s,))
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            drugs = [x["name"] for x in q(
                "SELECT d2.name FROM drugs d2 JOIN disease_drugs dd ON d2.id=dd.drug_id WHERE dd.disease_id=%s", (r["id"],))]
            knowledge += "疾病【%s %s】严重度%s，常用药物：%s。病因：%s\n" % (
                r["name"], "", r["severity"], "、".join(drugs), (r["cause"] or "")[:80])
    return knowledge


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def api_chat():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    question = (data.get("message") or "").strip()
    history = data.get("history", [])[-6:]  # 最近6条消息作为记忆

    if not question:
        return jsonify({"reply": "请输入您的问题"})

    # ① RAG 检索知识库
    knowledge = _retrieve_knowledge(question)

    # ② 组装消息
    system_prompt = (
        "你是『联邦医院知识图谱AI』的医疗助手，回答需遵守：\n"
        "1. 优先依据下面提供的知识库内容回答，知识库没有的信息不要编造；\n"
        "2. 用中文、口语化、分点简洁回答，控制在300字内；\n"
        "3. 结尾必须加一句：本回答仅供健康参考，不能替代执业医师诊断，如有不适请及时就医。\n"
    )
    if knowledge:
        system_prompt += "\n【知识库检索结果】\n" + knowledge
    else:
        system_prompt += "\n【知识库检索结果】未命中，请给出通用健康建议并建议用户就医咨询。"

    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        role = h.get("role")
        content = (h.get("content") or "")[:500]
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    # ③ 调用百炼（OpenAI 兼容接口）
    try:
        resp = _requests.post(
            BAILIAN_API_URL,
            headers={"Authorization": "Bearer " + BAILIAN_API_KEY,
                     "Content-Type": "application/json"},
            json={"model": BAILIAN_MODEL, "messages": messages,
                  "temperature": 0.7, "max_tokens": 800},
            timeout=60,
        )
        result = resp.json()
        if resp.status_code == 200:
            answer = result["choices"][0]["message"]["content"]
            return jsonify({"reply": answer, "knowledge_hit": bool(knowledge)})
        else:
            err = result.get("message") or result.get("error", {}).get("message", "未知错误")
            return jsonify({"reply": "AI 服务暂时不可用：" + str(err)}), 502
    except _requests.exceptions.Timeout:
        return jsonify({"reply": "AI 响应超时，请稍后重试"}), 504
    except Exception as e:
        return jsonify({"reply": "调用出错：" + str(e)[:200]}), 500


# ============================================================
# 拍照分析接口（v4.3 · qwen-vl 观察 + 知识规则层）
# ============================================================
import json as _json
import re as _re
import hashlib as _hashlib

_PHOTO_DISCLAIMER = "本结果为健康教育参考，不构成诊断，不能替代执业医师面诊；如有红旗症状请及时就医。"
_PHOTO_LEVEL_ORDER = {"自行处理": 0, "建议就医": 1, "尽快就医": 2}
_PHOTO_EMERGENCY_KW = ["大面积", "深部", "大量出血", "出血不止", "发热", "寒战", "呼吸", "过敏", "溃烂", "快速扩散", "迅速扩大"]

_PHOTO_WOUND_KB = [
    {"id": "abrasion", "name": "擦伤 / 划伤", "kw": ["擦伤", "擦破", "划伤", "刮伤", "表皮破损", "破损"],
     "level": "自行处理",
     "care": ["清水或生理盐水冲洗创面", "碘伏由内向外消毒", "保持干燥，必要时创可贴覆盖", "观察 48 小时有无红肿扩大"],
     "meds": ["碘伏", "红霉素软膏"],
     "alert": ["伤口较深 / 出血不止", "异物嵌入或污染严重", "红肿扩大、发热"]},
    {"id": "bruise", "name": "瘀伤 / 挫伤", "kw": ["瘀", "淤青", "挫伤", "皮下出血"],
     "level": "自行处理",
     "care": ["24 小时内冷敷（隔布，每次 15 分钟）", "48 小时后可温热敷促进吸收", "抬高患处，避免揉搓"],
     "meds": [],
     "alert": ["大面积瘀青或多发瘀斑", "剧烈疼痛 / 活动受限"]},
    {"id": "burn", "name": "烫伤 / 烧伤", "kw": ["烫伤", "烧伤", "灼伤"],
     "level": "建议就医",
     "care": ["流动冷水冲洗 15–20 分钟（勿用冰）", "不要涂牙膏 / 酱油等偏方", "清洁纱布覆盖，勿挑破水疱"],
     "meds": ["烧烫伤膏"],
     "alert": ["面积超过手掌 / 位于面部关节", "大水疱或皮肤发白", "儿童或老人"]},
    {"id": "rash", "name": "红肿 / 皮疹", "kw": ["皮疹", "红疹", "红肿", "红晕", "丘疹", "风团", "红斑"],
     "level": "自行处理",
     "care": ["避免抓挠与热水刺激", "记录近期接触物（食物 / 植物 / 化妆品）", "保持局部清洁干燥"],
     "meds": ["炉甘石洗剂"],
     "alert": ["皮疹快速扩散", "伴发热 / 呼吸困难", "面部肿胀"]},
    {"id": "bite", "name": "蚊虫叮咬", "kw": ["叮咬", "咬点", "蚊", "虫咬", "咬痕", "叮包"],
     "level": "自行处理",
     "care": ["肥皂水清洗叮咬处", "冷敷止痒，勿抓挠以防感染", "观察有无扩大或化脓"],
     "meds": ["炉甘石洗剂", "薄荷类止痒膏"],
     "alert": ["化脓 / 红线向近端蔓延", "发热、寒战", "大面积肿胀"]},
    {"id": "pus", "name": "脓包 / 溃疡", "kw": ["脓", "溃疡", "化脓", "渗液", "糜烂"],
     "level": "建议就医",
     "care": ["保持清洁，勿自行挤压", "纱布覆盖防污染", "尽快门诊评估"],
     "meds": ["莫匹罗星软膏"],
     "alert": ["创面扩大 / 深达皮下", "发热", "糖尿病等基础病人群"]},
    {"id": "blister", "name": "水疱", "kw": ["水疱", "水泡", "起泡"],
     "level": "自行处理",
     "care": ["勿挑破水疱，保持完整", "清洁纱布松覆盖", "摩擦部位减少活动"],
     "meds": [],
     "alert": ["大面积水疱", "疼痛加剧或渗液增多"]},
    {"id": "wasp", "name": "蜂蜇 / 严重过敏", "kw": ["蜂蜇", "蜂咬", "蜇伤", "蛰伤"],
     "level": "尽快就医",
     "care": ["迅速离开现场", "局部冷敷", "密切观察全身反应"],
     "meds": [],
     "alert": ["呼吸困难 / 喉咙发紧", "全身风团 / 头晕", "既往过敏史"]},
]

_PHOTO_INSECTS = [
    {"name": "蚊子", "kw": ["蚊子", "蚊"],
     "feature": "散在或成簇风团样红肿，中央细咬点，瘙痒明显",
     "scene": "四肢 / 颈周；傍晚户外后高发",
     "care": ["炉甘石止痒", "避免抓挠"],
     "alert": ["一般可自愈；化脓需就医"]},
    {"name": "跳蚤", "kw": ["跳蚤", "蚤"],
     "feature": "2–3 个成簇或成线的小红丘疹，中央小点常带结痂",
     "scene": "小腿 / 脚踝；接触宠物、地毯后",
     "care": ["环境除蚤", "瘙痒重时可口服抗组胺（遵医嘱 / 说明书）"],
     "alert": ["持续抓挠致感染"]},
    {"name": "臭虫", "kw": ["臭虫"],
     "feature": "典型『早餐-午餐-晚餐』线性三连咬",
     "scene": "床品接触部位；晨起发现",
     "care": ["检查床垫缝隙", "环境消杀害虫"],
     "alert": ["反复叮咬影响睡眠"]},
    {"name": "隐翅虫", "kw": ["隐翅虫"],
     "feature": "条状灼伤样红斑 / 水疱，疼痛明显",
     "scene": "面颈、四肢暴露处；夏秋夜间灯光下",
     "care": ["不拍打虫体，肥皂水冲洗", "勿挑破"],
     "alert": ["皮损范围大或继发感染请就医"]},
    {"name": "蜱虫", "kw": ["蜱虫", "蜱"],
     "feature": "虫体附着皮肤、无明显痛感；周围可现环形红斑",
     "scene": "草丛 / 林区活动史",
     "care": ["不要硬拔或用火烤"],
     "alert": ["尽快就医完整拔除", "观察发热（警惕蜱传疾病）"]},
    {"name": "蜂 / 蚂蚁", "kw": ["蜂", "蚂蚁", "蚁"],
     "feature": "剧痛、即刻红肿；蜂蜇中央可见刺点",
     "scene": "户外；蜂群 / 蚁群活动区",
     "care": ["局部冷敷", "取出可见毒刺（刮除而非捏压）"],
     "alert": ["过敏史者警惕全身反应 → 急诊"]},
    {"name": "螨虫", "kw": ["螨"],
     "feature": "密集小丘疹，夜间瘙痒加重",
     "scene": "床品 / 衣物接触区",
     "care": ["清洗暴晒床品", "环境除螨"],
     "alert": ["继发感染需就医"]},
]

_PHOTO_MEDS = {
    "碘伏": {"usage": "创面消毒，由内向外涂抹", "note": "开放性深创面请先就医处理"},
    "生理盐水": {"usage": "冲洗清洁创面", "note": "开封后尽快使用"},
    "红霉素软膏": {"usage": "小面积浅表创面防感染", "note": "过敏者禁用；连用不超过 1 周"},
    "莫匹罗星软膏": {"usage": "小面积脓疱 / 感染创面", "note": "遵说明书；扩大或发热时就医"},
    "炉甘石洗剂": {"usage": "止痒收敛（叮咬 / 轻度皮疹）", "note": "破损皮肤慎用"},
    "薄荷类止痒膏": {"usage": "叮咬止痒", "note": "婴幼儿慎用，避免接触眼口"},
    "烧烫伤膏": {"usage": "轻度烫伤表面护理", "note": "大水疱 / 大面积先就医"},
    "抗组胺口服药": {"usage": "过敏瘙痒较重时", "note": "遵医嘱或说明书；驾驶前慎用"},
}


def _photo_json(text):
    m = _re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        return _json.loads(m.group(0))
    except Exception:
        return None


def _photo_rules(vl):
    feats = [str(x) for x in (vl.get("features") or [])]
    causes = [str(x) for x in (vl.get("likely_cause") or [])]
    text = " ".join([str(vl.get("condition") or "")] + feats + causes + [str(vl.get("note") or "")])
    insects = []
    for ins in _PHOTO_INSECTS:
        if any((k in text) or any(k in c for c in causes) for k in ins["kw"]):
            insects.append(ins)
    insects = insects[:3]
    wound = None
    for w in _PHOTO_WOUND_KB:
        if any(k in text for k in w["kw"]):
            wound = w
            break
    if insects and (wound is None or wound["id"] == "rash"):
        wound = next((w for w in _PHOTO_WOUND_KB if w["id"] == "bite"), wound)
    base = _PHOTO_LEVEL_ORDER.get(str(vl.get("advice_level") or ""), 0)
    if wound:
        base = max(base, _PHOTO_LEVEL_ORDER.get(wound["level"], 0))
    if any(k in text for k in _PHOTO_EMERGENCY_KW):
        base = max(base, 1)
    if "蜱" in text:
        base = max(base, 2)
    for k in ["出血不止", "大量出血", "呼吸困难", "意识", "昏厥"]:
        if k in text:
            base = max(base, 2)
    level = "自行处理"
    for k, v in _PHOTO_LEVEL_ORDER.items():
        if v == base:
            level = k
            break
    care = list(wound["care"]) if wound else []
    for ins in insects:
        for c in ins["care"]:
            if c not in care:
                care.append(c)
    if not care:
        care = ["保持局部清洁，避免抓挠", "观察 48 小时变化，加重及时就医"]
    meds = []
    names = (list(wound["meds"]) if wound else [])
    if insects and "炉甘石洗剂" not in names:
        names.append("炉甘石洗剂")
    for n in names:
        info = _PHOTO_MEDS.get(n)
        if info:
            meds.append({"name": n, "usage": info["usage"], "note": info["note"]})
    red = []
    for x in (vl.get("red_flags") or []) + (wound["alert"] if wound else []) + [a for i in insects for a in i["alert"]]:
        if x and x not in red:
            red.append(x)
    return {
        "mapped": {"wound": wound["name"] if wound else None, "insects": [i["name"] for i in insects]},
        "level": level,
        "care": care[:7],
        "meds": meds[:5],
        "red_flags": red[:6],
        "insects": [{"name": i["name"], "feature": i["feature"], "scene": i["scene"], "care": i["care"], "alert": i["alert"]} for i in insects],
    }


_PHOTO_CACHE = {}


@app.route("/api/photo/analyze", methods=["POST", "OPTIONS"])
def api_photo_analyze():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    img = data.get("image") or ""
    if not (isinstance(img, str) and img.startswith("data:image")):
        return jsonify({"ok": False, "error": "请提供图片（data:image/... base64 格式）"}), 400
    if len(img) > 8000000:
        return jsonify({"ok": False, "error": "图片过大，请压缩后重试（建议小于 5MB）"}), 400
    ck = _hashlib.md5(img.encode("utf-8")).hexdigest()
    if ck in _PHOTO_CACHE:
        return jsonify(_PHOTO_CACHE[ck])
    prompt = ("这是一张皮肤患处照片。请只输出 JSON（不要其他文字）："
              '{"condition":"皮肤表现的一句话描述","likely_cause":["若疑似叮咬，列出可能的昆虫来源，最多3个；否则空数组"],'
              '"confidence":"推断置信度 低/中/高","severity":"轻度/中度/重度","features":["观察到的主要特征，2-6条"],'
              '"advice_level":"自行处理/建议就医/尽快就医","red_flags":["需要警惕的情况，0-4条"],"note":"一句话补充"}')
    try:
        resp = _requests.post(
            BAILIAN_API_URL,
            headers={"Authorization": "Bearer " + BAILIAN_API_KEY, "Content-Type": "application/json"},
            json={"model": "qwen-vl-plus", "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": img}}]}], "temperature": 0.2},
            timeout=120,
        )
        if resp.status_code != 200:
            return jsonify({"ok": False, "error": "视觉分析服务暂时不可用（HTTP " + str(resp.status_code) + "）"}), 502
        content = resp.json()["choices"][0]["message"]["content"]
        vl = _photo_json(content) or {"condition": (content or "")[:120], "features": [], "advice_level": "自行处理"}
    except Exception as e:
        return jsonify({"ok": False, "error": "分析调用失败：" + str(e)[:150]}), 500
    rules = _photo_rules(vl)
    result = {
        "ok": True, "analysis": vl, "mapped": rules["mapped"], "level": rules["level"],
        "care": rules["care"], "meds": rules["meds"], "red_flags": rules["red_flags"],
        "insects": rules["insects"], "disclaimer": _PHOTO_DISCLAIMER,
    }
    _PHOTO_CACHE[ck] = result
    return jsonify(result)


@app.route("/sample/<fn>")
def photo_sample(fn):
    if fn not in ("sample_wound.jpg", "sample_bite.jpg"):
        return ("not found", 404)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), fn)
    if not os.path.exists(p):
        return ("not found", 404)
    with open(p, "rb") as f:
        data = f.read()
    return app.response_class(data, mimetype="image/jpeg")


if __name__ == "__main__":
    print("=" * 50)
    print("  联邦医院知识图谱AI — 后端已启动")
    print("  访问: http://localhost:5000")
    print("  API 列表:")
    print("    GET  /api/hospitals       — 医院列表")
    print("    GET  /api/diseases        — 疾病列表")
    print("    GET  /api/symptoms        — 症状列表")
    print("    POST /api/diagnose        — 症状推理")
    print("    GET  /api/graph           — 知识图谱")
    print("    GET  /api/cases           — 模拟病例")
    print("    GET  /api/stats           — 医院统计")
    print("    GET  /api/overview        — 全部概览")
    print("    POST /api/login        — 登录（7 医院账号）")
    print("    POST /api/logout       — 退出登录")
    print("    GET  /api/me           — 会话查询")
    print("    GET  /api/fl/train     — 联邦训练（FedAvg 演示）")
    print("    GET  /legacy           — 旧版页面（保留通道）")
    print("=" * 50)
    app.run(host="127.0.0.1", port=5000, debug=True)
