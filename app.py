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
    print("=" * 50)
    app.run(host="127.0.0.1", port=5000, debug=True)
