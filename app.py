# -*- coding: utf-8 -*-
"""
联邦医院知识图谱AI — Flask + MySQL 后端（v4.8 病历档案版）
- 应用台：/app（侧栏导航 + 登录/注册 + 移动端直达）
- 图谱：本院视图 / 联邦聚合视图（各院贡献可见，含示意口径标注）
- 诊断：接入联邦全局模型（真 FedAvg · 版本化 · 可切回基础公式）
- 安全：业务接口登录鉴权 + 本院数据隔离 + 未知医院校验
访问: http://localhost:5000
"""

from flask import Flask, render_template_string, request, jsonify, make_response, redirect
import pymysql
import random
import os

app = Flask(__name__)

# ── 配置加载（v4.9.3）：支持项目根目录 .env 文件与环境变量，便于复现与部署 ──
# 优先级：环境变量 > .env 文件 > 代码内默认值（默认值即原有本地配置，向后兼容）
def _load_dotenv():
    """读取项目根目录 .env（简易解析，无需额外依赖）；已存在的环境变量不覆盖。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        print("[配置] 已加载 .env")
    except Exception as e:
        print("[配置] .env 读取失败：%s" % e)


_load_dotenv()

DB = {
    "host": os.environ.get("HG_DB_HOST", "localhost"),
    "user": os.environ.get("HG_DB_USER", "root"),
    "password": os.environ.get("HG_DB_PASSWORD", ""),
    "database": os.environ.get("HG_DB_NAME", "hospital_graph"),
    "charset": "utf8",
    "cursorclass": pymysql.cursors.DictCursor,
}

# ── CORS 全局处理 ──

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ── 数据库工具函数 ──

class _DBError(Exception):
    """数据库不可用（统一转 503 JSON）"""
    pass


def q(sql, *args):
    """执行查询并返回所有行"""
    try:
        db = pymysql.connect(**DB)
        cur = db.cursor()
        cur.execute(sql, args)
        rows = cur.fetchall()
        db.close()
        return rows
    except pymysql.MySQLError as e:
        raise _DBError(str(e)[:200])


def ex(sql, *args):
    """执行写操作"""
    try:
        db = pymysql.connect(**DB)
        cur = db.cursor()
        cur.execute(sql, args)
        db.commit()
        db.close()
    except pymysql.MySQLError as e:
        raise _DBError(str(e)[:200])


# ── 统一 JSON 错误处理（API 契约：JSON 进、JSON 出）──

@app.errorhandler(_DBError)
def _h_db_error(e):
    return jsonify({"ok": False, "error": "数据库暂不可用，请稍后重试"}), 503


@app.errorhandler(404)
def _h_notfound(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "接口不存在"}), 404
    return e


@app.errorhandler(405)
def _h_notallowed(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "请求方法不允许"}), 405
    return e


@app.errorhandler(Exception)
def _h_uncaught(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    print("[未捕获异常]", repr(e))
    return jsonify({"ok": False, "error": "服务内部错误，请稍后重试"}), 500


app.config["PROPAGATE_EXCEPTIONS"] = False

# ── 首页 ──

@app.route("/")
def index():
    _mr = _mobile_redirect()
    if _mr is not None:
        return _mr
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


# ── API: 症状推理诊断（三因素加权 · 联邦全局模型接入 · 需登录）──

def _dx_differential(did, ds_symptoms, dx_syms, diseases):
    """v4.9：按「共享症状数」给出易混淆病种（知识图谱的鉴别维度），返回 [{name, shared, common:[...]}]"""
    mine = set(ds_symptoms)
    out = []
    for d2 in diseases:
        if d2["id"] == did:
            continue
        other = set(dx_syms.get(d2["id"], []))
        common = mine & other
        if len(common) >= 2:
            out.append({"name": d2["name"], "dept": d2["dept"], "shared": len(common),
                        "common": sorted(common)})
    out.sort(key=lambda x: (-x["shared"], x["name"]))
    return out


@app.route("/api/diagnose", methods=["POST"])
def api_diagnose():
    acc = _sess(request)
    if not acc:
        return _deny()
    # v4.10 复核修复（F1）：联邦中心不看病——诊断面向医院账号
    # （另：ALL 口径下各病发病率兜底 0.05，特例预警的 rate < 0.05 恒为假、会静默失效）
    if acc.get("center"):
        return jsonify({"ok": False, "error": "诊断面向医院账号：联邦中心不看病（中心只做参数聚合）"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须为 JSON 对象"}), 400
    raw = data.get("symptoms", [])
    if not isinstance(raw, list):
        return jsonify({"ok": False, "error": "symptoms 必须为字符串数组"}), 400
    symptoms = []
    for s in raw:
        if isinstance(s, str):
            s = s.strip()
            if s and s not in symptoms:
                symptoms.append(s)
    if not symptoms:
        return jsonify([])
    hospital_id, err = _resolve_hospital(acc, data.get("hospital_id"))
    if err:
        return err
    model_sel = str(data.get("model") or "global").lower()

    # 联邦能力层：全局模型（训练完成后自动生效；model=baseline 可切回基础公式）
    W = None
    used = None
    if model_sel != "baseline" and _MODEL.get("w"):
        W = _MODEL["w"]
        used = {
            "mode": "federated",
            "version": _MODEL.get("version", 1),
            "params": _MODEL.get("params", 0),
        }

    diseases = q("SELECT * FROM diseases")
    # v4.9：一次性取全部病-症关系（替代按病逐条的 N+1 查询），同时用于鉴别疾病计算
    _dx_syms = {}
    for _r in q("SELECT ds.disease_id AS did, s.name AS nm FROM disease_symptoms ds "
                "JOIN symptoms s ON s.id = ds.symptom_id"):
        _dx_syms.setdefault(_r["did"], []).append(_r["nm"])
    _dx_meta = {}   # v4.10（P2）：各病评分元数据，供特例预警判定
    results = []
    for d in diseases:
        ds_symptoms = _dx_syms.get(d["id"], [])
        matched_syms = [s for s in symptoms if s in ds_symptoms]
        matched = len(matched_syms)
        if matched == 0:
            continue

        # 症状匹配度（60%）：全局模型 → 按学得的症状权重加权；否则基础公式（均钳制 ≤1）
        # v4.9：同时记录每个命中症状的权重与贡献占比，供前端展示「为什么是这个分」
        contributions = []
        if W is not None and d["name"] in W:
            wd = W[d["name"]]
            w_all = {s: float(wd.get(s, 1.0)) for s in ds_symptoms}
            num = sum(w_all.get(s, 1.0) for s in matched_syms)
            den = sum(w_all.values()) or 1.0
            sm_score = min(1.0, num / den)
            for s in matched_syms:
                w_s = w_all.get(s, 1.0)
                contributions.append({
                    "symptom": s,
                    "weight": round(w_s, 3),
                    "share": round(w_s / den, 4),
                })
        else:
            sm_score = min(1.0, matched / max(len(ds_symptoms), 1))
            den0 = max(len(ds_symptoms), 1)
            for s in matched_syms:
                contributions.append({
                    "symptom": s,
                    "weight": 1.0,
                    "share": round(1.0 / den0, 4),
                })
        contributions.sort(key=lambda x: x["share"], reverse=True)
        contributions = contributions[:8]

        # 本地发病率 (20%)
        rate_row = q(
            "SELECT rate FROM prevalence_rates WHERE disease_id = %s AND hospital_id = %s",
            d["id"],
            hospital_id,
        )
        avg_rate = float(rate_row[0]["rate"]) if rate_row else 0.05
        br_score = min(avg_rate * 5, 1)
        _dx_meta[d["name"]] = {"matched": matched, "total": len(ds_symptoms), "rate": avg_rate}

        # 严重度 (20%)
        sv_map = {"危急": 1.0, "严重": 0.7, "中度": 0.5, "轻度": 0.3}
        sv_score = sv_map.get(d["severity"], 0.5)

        score = min(100, round((sm_score * 0.6 + br_score * 0.2 + sv_score * 0.2) * 100))
        score_base = min(100, round(
            (min(1.0, matched / max(len(ds_symptoms), 1)) * 0.6 + br_score * 0.2 + sv_score * 0.2) * 100
        ))
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
                    "score_base": score_base if W is not None else None,
                    "model_ver": used["version"] if used else None,
                    "matched": matched,
                    "total": len(ds_symptoms),
                    "drugs": drugs,
                    "tests": tests,
                    "prevention": prevs,
                    "cause": d["cause"],
                    "urgent": d["severity"] in ("危急", "严重"),
                    # ── v4.9 可解释性：三因素拆解 + 症状贡献 + 鉴别疾病 ──
                    "factors": [
                        {"key": "symptom", "label": "症状匹配", "weight": 0.6,
                         "raw": round(sm_score, 4), "points": round(sm_score * 60, 1),
                         "detail": "命中 %d/%d 个关联症状%s" % (
                             matched, len(ds_symptoms),
                             ("，按模型学到的重要度加权" if (W is not None and d["name"] in W) else "，基础版按等权计"))},
                        {"key": "prevalence", "label": "本院发病率", "weight": 0.2,
                         "raw": round(br_score, 4), "points": round(br_score * 20, 1),
                         "detail": "本院历史发病率 %s%%" % round(avg_rate * 100, 2)},
                        {"key": "severity", "label": "严重度", "weight": 0.2,
                         "raw": round(sv_score, 4), "points": round(sv_score * 20, 1),
                         "detail": "病种严重度：%s" % d["severity"]},
                    ],
                    "contributions": contributions,
                    "differential": _dx_differential(d["id"], ds_symptoms, _dx_syms, diseases)[:3],
                }
            )

    results.sort(key=lambda x: x["score"], reverse=True)

    # ── v4.10（P2）特例预警：规则层安全网 ──
    # 症状高度吻合（覆盖 ≥ _ALERT_COV 且命中 ≥ _ALERT_MIN_HIT）但本院罕见（< _ALERT_RATE）、
    # 且不是首推（排名 > _ALERT_TOPN）→ 独立预警：首推常见病时提醒勿漏罕见病，
    # 防止个例被「发病率因子 × 统计平均」结构性稀释而漏诊。
    alerts = []
    for _i, _r in enumerate(results):
        if _i < _ALERT_TOPN:
            continue
        _m = _dx_meta.get(_r["disease"]) or {}
        _cov = _m.get("matched", 0) / max(_m.get("total", 1), 1)
        if _m.get("matched", 0) >= _ALERT_MIN_HIT and _cov >= _ALERT_COV and _m.get("rate", 1) < _ALERT_RATE:
            alerts.append({
                "disease": _r["disease"], "dept": _r["dept"], "severity": _r["severity"],
                "coverage": "%d/%d" % (_m["matched"], _m["total"]), "cov": round(_cov, 3),
                "local_rate": round(_m["rate"] * 100, 2), "rank": _i + 1, "score": _r["score"],
                "tests": (_r.get("tests") or [])[:3],
                "top1": results[0]["disease"] if results else None,
            })
    alerts.sort(key=lambda a: a["cov"], reverse=True)
    alerts = alerts[:2]
    if alerts:
        _by = {a["disease"]: a for a in alerts}
        out = []
        for _r in results[:6]:
            if _r["disease"] in _by:
                _r = dict(_r, special_alert=_by[_r["disease"]])
            out.append(_r)
        _seen = {r["disease"] for r in out}
        for a in alerts:
            if a["disease"] not in _seen:
                _src = next(x for x in results if x["disease"] == a["disease"])
                out.append(dict(_src, special_alert=a))
        return jsonify(out)
    return jsonify(results[:6])

# ── API: 知识图谱（节点 + 边 · 联邦聚合：本院贡献 / 六院并集）──

_FED_HIDS = ["A", "B", "C", "D", "E", "F"]


def _h_rand(*parts):
    """确定性伪随机（同一条关联每次生成的权重/覆盖一致）"""
    h = _hashlib.md5(("|".join(str(p) for p in parts)).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _contrib(key):
    """一条关联的『各院贡献』：覆盖 2–6 院，每院 2–29 例（演示级聚合口径）"""
    cov = 2 + _h_rand("cov", key) % 5
    rot = _h_rand("rot", key) % len(_FED_HIDS)
    order = _FED_HIDS[rot:] + _FED_HIDS[:rot]
    out = {}
    for hh in order[:cov]:
        out[hh] = 2 + _h_rand("w", key, hh) % 28
    return out


def _contrib_all(key):
    """六院共识关联（核心症状/药物/检查：各院均有病例支持）"""
    return {hh: 3 + _h_rand("w", key, hh) % 20 for hh in _FED_HIDS}


def _build_graph(scope="fed", hospital="A"):
    nodes, edges, nm, nid = [], [], {}, 0

    def add_node(label, ntype):
        nonlocal nid
        if label in nm:
            return nm[label]
        nm[label] = nid
        nodes.append({"id": nid, "label": label, "type": ntype})
        nid += 1
        return nid - 1

    def push_edge(sid, tid, kind, key, core=False):
        contrib = _contrib_all(key) if core else _contrib(key)
        edges.append({
            "source": sid, "target": tid, "kind": kind,
            "hospitals": contrib, "covers": len(contrib),
            "w": sum(contrib.values()),
        })

    diseases = q("SELECT * FROM diseases ORDER BY id")
    for d in diseases:
        did = add_node(d["name"], "disease")
        add_node(d["dept"], "dept")
        _dept_c = _contrib_all("dept|" + d["name"])
        edges.append({
            "source": did, "target": nm[d["dept"]], "kind": "dept",
            "hospitals": _dept_c, "covers": len(_FED_HIDS),
            "w": sum(_dept_c.values()),
        })

        syms = [x["name"] for x in q(
            "SELECT s.name FROM symptoms s "
            "JOIN disease_symptoms ds ON s.id = ds.symptom_id "
            "WHERE ds.disease_id = %s ORDER BY s.id", d["id"])]
        for i, s in enumerate(syms):
            push_edge(did, add_node(s, "symptom"), "symptom", "sym|%s|%s" % (d["name"], s), core=(i == 0))

        drs = [x["name"] for x in q(
            "SELECT d2.name FROM drugs d2 "
            "JOIN disease_drugs dd ON d2.id = dd.drug_id "
            "WHERE dd.disease_id = %s ORDER BY d2.id", d["id"])]
        for i, dr in enumerate(drs):
            push_edge(did, add_node(dr, "drug"), "drug", "drug|%s|%s" % (d["name"], dr), core=(i == 0))

        tss = [x["name"] for x in q(
            "SELECT t.name FROM tests t "
            "JOIN disease_tests dt ON t.id = dt.test_id "
            "WHERE dt.disease_id = %s ORDER BY t.id", d["id"])]
        for i, t in enumerate(tss):
            push_edge(did, add_node(t, "test"), "test", "test|%s|%s" % (d["name"], t), core=(i == 0))

    degraded = False
    total_edges = len(edges)
    if scope == "local" and hospital in _FED_HIDS:
        kept = []
        for e in edges:
            if hospital in e["hospitals"]:
                e2 = dict(e)
                e2["w"] = e["hospitals"][hospital]
                kept.append(e2)
        edges = kept
    elif scope == "local":
        # 联邦中心等全局账号：本院视图退化为联邦聚合视图
        scope = "fed"
        degraded = True

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "scope": scope,
            "hospital": hospital,
            "hospitals_total": len(_FED_HIDS),
            "edges_total_fed": total_edges,
            "edges_in_view": len(edges),
            "synthetic": True,
            "degraded": degraded,
        },
    }


@app.route("/api/graph")
def api_graph():
    acc = _sess(request)
    if not acc:
        return _deny()
    scope = (request.args.get("scope") or "fed").lower()
    if scope not in ("fed", "local"):
        scope = "fed"
    hospital, err = _resolve_hospital(acc, request.args.get("hospital"))
    if err:
        return err
    return jsonify(_build_graph(scope, hospital))

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
    acc = _sess(request)
    if not acc:
        return _deny()
    hospital_id, err = _resolve_hospital(acc, request.args.get("hospital"))
    if err:
        return err
    cases = _generate_cases(hospital_id)
    return jsonify(cases)

# ── API: 医院统计 ──

@app.route("/api/stats")
def api_stats():
    acc = _sess(request)
    if not acc:
        return _deny()
    hospital_id, err = _resolve_hospital(acc, request.args.get("hospital"))
    if err:
        return err
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

# ── API: 所有医院概览（仅联邦中心）──

@app.route("/api/overview")
def api_overview():
    acc = _sess(request)
    if not acc:
        return _deny()
    if not acc.get("center"):
        return jsonify({"ok": False, "error": "仅联邦中心账号可查看六院概览"}), 403
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
    "demo":     {"pw": "demo2026", "hospital": "A", "name": "演示用户", "role": "user", "center": False},
}

_SESSIONS = {}  # token -> 会话信息
_SESS_TTL = 24 * 3600


def _tok(req):
    return req.headers.get("X-Token") or req.args.get("token") or ""


def _sess(req):
    """返回登录账号 dict（滑动续期 + 过期清理）；未登录返回 None"""
    tk = _tok(req)
    s = _SESSIONS.get(tk)
    if not s:
        return None
    if _time.time() - s["ts"] > _SESS_TTL:
        _SESSIONS.pop(tk, None)
        return None
    s["ts"] = _time.time()
    acc = _ACCOUNTS.get(s["username"])
    if acc is not None:
        acc = dict(acc)
    else:
        u = _RUSERS.get(s["username"])
        if u is not None:
            acc = {"hospital": u.get("hospital") or "A", "name": u.get("name") or s["username"],
                   "role": "user", "center": False}
    if acc is not None:
        acc["username"] = s["username"]
    return acc


def _deny(msg="未登录或会话已失效，请重新登录"):
    return jsonify({"ok": False, "error": msg}), 401


def _resolve_hospital(acc, wanted):
    """医院标识白名单 + 权限校验。
    返回 (resolved, None) 或 (None, (resp, code))。
    规则：缺省 = 本院；未知 = 400；普通账号访问他院 / ALL = 403；中心账号可任意。"""
    w = str(wanted or "").strip().upper()
    if not w:
        w = acc["hospital"]
    if w not in _FED_HIDS and w != "ALL":
        return None, (jsonify({"ok": False, "error": "未知医院标识（仅支持 A–F，中心可用 ALL）"}), 400)
    if acc.get("center"):
        return w, None
    if w == "ALL" or w != acc["hospital"]:
        return None, (jsonify({"ok": False, "error": "无权访问其他机构数据"}), 403)
    return w, None


# ── 用户注册（v4.7 应用台）：注册用户存 data/users.json（盐 + SHA-256） ──

_USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "users.json")
_RUSERS = {}  # username -> {salt, hash, name, hospital, created}


def _rusers_load():
    try:
        if os.path.exists(_USERS_FILE):
            with open(_USERS_FILE, encoding="utf-8") as f:
                blob = _fjson.load(f)
            for k, v in (blob.get("users") or {}).items():
                if isinstance(v, dict) and v.get("salt") and v.get("hash"):
                    _RUSERS[k] = v
            print("[v4.7] 已加载注册用户：%d 个" % len(_RUSERS))
    except Exception as e:
        print("[v4.7] 注册用户加载失败：%s" % e)


def _rusers_save():
    try:
        os.makedirs(os.path.dirname(_USERS_FILE), exist_ok=True)
        tmp = _USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _fjson.dump({"users": _RUSERS}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _USERS_FILE)
    except Exception as e:
        print("[v4.7] 注册用户保存失败：%s" % e)


def _pw_check(u, password):
    try:
        salt = str(u.get("salt") or "")
        got = _hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return got == u.get("hash")
    except Exception:
        return False


def _find_account(username):
    """统一账号查询（内置演示账号 + 注册用户）→ 安全字段 dict 或 None"""
    acc = _ACCOUNTS.get(username)
    if acc is not None:
        return {"hospital": acc["hospital"], "name": acc["name"], "role": acc["role"], "center": acc["center"]}
    u = _RUSERS.get(username)
    if u is not None:
        return {"hospital": u.get("hospital") or "A", "name": u.get("name") or username,
                "role": "user", "center": False}
    return None


@app.route("/api/login", methods=["POST", "OPTIONS"])
def api_login():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须为 JSON 对象"}), 400
    u_raw, p_raw = data.get("username"), data.get("password")
    if not isinstance(u_raw, str) or not isinstance(p_raw, str):
        return jsonify({"ok": False, "error": "用户名与密码必须为字符串"}), 400
    username = u_raw.strip().lower()
    password = p_raw.strip()
    ok_pw = False
    if username in _ACCOUNTS:
        ok_pw = (password == _ACCOUNTS[username]["pw"])
    elif username in _RUSERS:
        ok_pw = _pw_check(_RUSERS[username], password)
    if not ok_pw:
        return jsonify({"ok": False, "error": "账号或密码错误"}), 401
    info = _find_account(username) or {}
    token = _uuid.uuid4().hex
    _SESSIONS[token] = {"username": username, "ts": _time.time()}
    return jsonify({
        "ok": True, "token": token,
        "user": {"username": username, "hospital": info.get("hospital"), "name": info.get("name"),
                 "role": info.get("role"), "center": info.get("center")},
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
    acc = _find_account(sess["username"]) or {}
    return jsonify({
        "ok": True,
        "user": {"username": sess["username"], "hospital": acc.get("hospital"), "name": acc.get("name"),
                 "role": acc.get("role"), "center": acc.get("center")},
    })

@app.route("/api/register", methods=["POST", "OPTIONS"])
def api_register():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须为 JSON 对象"}), 400
    u_raw, p_raw = data.get("username"), data.get("password")
    if not isinstance(u_raw, str) or not isinstance(p_raw, str):
        return jsonify({"ok": False, "error": "用户名与密码必须为字符串"}), 400
    username = u_raw.strip().lower()
    password = p_raw.strip()
    name = str(data.get("name") or "").strip()[:20]
    hospital = str(data.get("hospital") or "A").strip().upper()
    _uchars = "abcdefghijklmnopqrstuvwxyz0123456789_"
    if not (3 <= len(username) <= 20) or any(ch not in _uchars for ch in username):
        return jsonify({"ok": False, "error": "用户名需为 3–20 位字母 / 数字 / 下划线"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "密码至少 6 位"}), 400
    if hospital not in _FED_HIDS:
        return jsonify({"ok": False, "error": "所属院区无效（仅支持 A–F）"}), 400
    if username in _ACCOUNTS or username in _RUSERS:
        return jsonify({"ok": False, "error": "该用户名已被占用"}), 409
    salt = os.urandom(16).hex()
    pw_hash = _hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    _RUSERS[username] = {"salt": salt, "hash": pw_hash, "name": name or username,
                         "hospital": hospital, "created": _ftime.strftime("%Y-%m-%d %H:%M:%S")}
    _rusers_save()
    token = _uuid.uuid4().hex
    _SESSIONS[token] = {"username": username, "ts": _time.time()}
    return jsonify({
        "ok": True, "token": token,
        "user": {"username": username, "hospital": hospital, "name": name or username,
                 "role": "user", "center": False},
    })



# ── 新版设计页（v4：登录已接入后台鉴权，离线时自动回退本地校验）──

@app.route("/v4")
def v4_page():
    # 与 / 同一渲染管线（历史上为双文件，现统一渲染 index.html，避免双份漂移）
    _mr = _mobile_redirect()
    if _mr is not None:
        return _mr
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(html_path, encoding="utf-8") as f:
        return render_template_string(f.read())


@app.route("/legacy")
def legacy_page():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index_legacy.html")
    with open(p, encoding="utf-8") as f:
        return f.read()

# ── 应用台（v4.7）：App 式界面 + 移动端直达 ──

_MOBILE_UA_KEYS = ("android", "iphone", "ipad", "ipod", "mobile", "harmonyos", "windows phone")


def _mobile_redirect():
    """移动端访问落地页 → 直达应用台（?desktop=1 豁免，可查看完整版）"""
    if request.args.get("desktop") == "1":
        return None
    ua = (request.headers.get("User-Agent") or "").lower()
    if any(k in ua for k in _MOBILE_UA_KEYS):
        qs = request.query_string.decode("utf-8")
        return redirect("/app" + (("?" + qs) if qs else ""))
    return None


@app.route("/app")
def app_page():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.html")
    with open(p, encoding="utf-8") as f:
        return render_template_string(f.read())



# ============================================================
# 联邦能力层 v2（真实 FedAvg · 诊断评分模型 45 参数 + 模型下发）
# ============================================================
import json as _fjson
import time as _ftime

_FL_SPECS = [
    ("A", "中心医院", 120),
    ("B", "市第一人民医院", 90),
    ("C", "附属第三医院", 150),
    ("D", "省第二人民医院", 60),
    ("E", "妇幼保健院", 120),
    ("F", "开发区医院", 60),
]
_FL_HIDS = [s[0] for s in _FL_SPECS]
_FL_LR = 1.6
_FL_EPOCHS = 10
_FL_SOLO_EPOCHS = 40

# ── v4.9：训练超参对外口径（供落地页/工作台显示，避免两套数字）──
_FL_SUMMARY = {
    "lr": _FL_LR,
    "epochs": _FL_EPOCHS,
    "solo_epochs": _FL_SOLO_EPOCHS,
    "aggregate": "FedAvg（按样本量加权）",
    "rounds_default": 15,
}

# ── v4.10（P2）：特例预警 + 罕见样本加权 ──
# 背景：评分 = 症状×0.6 + 本院发病率×0.2 + 严重度×0.2。罕见病（如急性胆囊炎本院 2–6%）
# 在发病率因子上结构性吃亏（因子 = 发病率×5，封顶 1），症状高度吻合时综合排名仍可能被
# 常见病压住、甚至被统计平均淹没。两层对策：
#   ① 推理层：规则式「特例预警」——不依赖模型概率，命中核心症状且罕见即独立预警；
#   ② 训练层：罕见病反馈样本按 _RARE_BOOST_K 倍复制进本地训练集（代价敏感学习），
#      对冲「个例占比过低被稀释」；聚合权重仍按唯一样本数计，不放大该院全局话语权。
_ALERT_COV = 0.7      # 预警：核心症状覆盖率下限
_ALERT_MIN_HIT = 3    # 预警：至少命中 3 个核心症状
_ALERT_RATE = 0.05    # 预警：本院发病率上限（<5% 视为罕见）
_ALERT_TOPN = 1      # 已排前 N 名（首推）不预警；首推为常见病而罕见病高度吻合时触发
_RARE_BOOST_K = 3     # 罕见病反馈样本训练复制倍数（1 = 关闭）
_RARE_RATE = 0.05     # 罕见病阈值（与预警口径一致）

# ── v4.10（P3）：投喂台 · 探针病例与聚合权重 ──
# 探针 = 固定症状组合：投喂前后各跑一次「AI 辅助诊断」同口径评分，对比排名变化。
# tb 探针对应 P2 特例预警的演示位（肺结核去「咯血」，首推常见病肺炎、肺结核屈居第 2）。
_V410_PROBES = [
    {"id": "tb", "label": "不典型呼吸道症状（无咯血）", "target": "肺结核",
     "symptoms": ["发热", "咳嗽", "咳痰", "体重下降", "盗汗"]},
    {"id": "gd", "label": "胆道急腹症（无黄疸）", "target": "急性胆囊炎",
     "symptoms": ["恶心", "发热", "呕吐", "右上腹痛"]},
    {"id": "pn", "label": "典型肺炎（对照）", "target": "肺炎",
     "symptoms": ["呼吸困难", "发热", "咳嗽", "咳痰"]},
]


def _fl_sample_ns():
    """v4.10（P3）：各院当前唯一参训样本数（基础配额 + 本院反馈累计，不含加权复制）"""
    return {h: n + len(_FEEDBACK.get(h, [])) for h, _, n in _FL_SPECS}


def _fl_weights():
    """v4.10（P3）：各院 FedAvg 聚合权重 = n院 / N（数据越多，影响越大）"""
    _ns = _fl_sample_ns()
    _tot = float(sum(_ns.values())) or 1.0
    return {h: round(v / _tot, 4) for h, v in _ns.items()}

# ── v4.9：差分隐私（DP-SGD 风格）常量与状态 ──
# 机制：客户端每轮先按阈值 C 裁剪参数更新，再叠加高斯噪声 N(0, σ²C²)，
#       理论隐私预算按经典高斯机制 ε = Δf·sqrt(2·ln(1.25/δ))/σ 估计（Δf = C）。
_DP_CLIP = 4.0            # 参数更新裁剪阈值 C
_DP_DELTA = 1e-5          # 目标 δ
_DP_SIGMAS = [0.0, 0.2, 0.5, 1.0, 2.0]   # 对比用噪声倍数（0 = 无噪声基线）
_DP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fed_dp.json")
_DP_LAST = None

_MODEL = {
    "w": None,
    "version": 0,
    "trained_at": None,
    "params": 0,
    "rounds": 0,
    "loss": None,
    "loss_base": None,
    "acc": None,
}
_FL_LAST = None
_MODEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fed_model.json")
_FL_LAST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fed_last.json")


def _load_model():
    try:
        if os.path.exists(_MODEL_FILE):
            with open(_MODEL_FILE, encoding="utf-8") as f:
                blob = _fjson.load(f)
            if blob.get("w"):
                _MODEL.update(blob)
                print("[联邦能力层] 已加载全局模型 v%s（%s 个参数）" % (blob.get("version"), blob.get("params")))
    except Exception as e:
        print("[联邦能力层] 模型加载失败：%s" % e)


def _save_model():
    try:
        os.makedirs(os.path.dirname(_MODEL_FILE), exist_ok=True)
        _atomic_write(_MODEL_FILE, _MODEL)
        if _FL_LAST is not None:
            _atomic_write(_FL_LAST_FILE, _FL_LAST)
    except Exception as e:
        print("[联邦能力层] 模型保存失败：%s" % e)

def _fed_dataset():
    """构建六院训练集（合成模拟 + 本地反馈样本）与留出集；各院先验不同（Non-IID）"""
    import numpy as _fnp
    rng = _fnp.random.RandomState(20261003)
    rng_h = _fnp.random.RandomState(77203)
    diseases = q("SELECT * FROM diseases ORDER BY id")
    names = [d["name"] for d in diseases]
    nidx = {n: i for i, n in enumerate(names)}
    D = len(names)
    syms = [r["name"] for r in q("SELECT name FROM symptoms ORDER BY id")]
    sidx = {s: i for i, s in enumerate(syms)}
    S = len(syms)
    dsyms = []
    for d in diseases:
        dsyms.append([sidx[x["name"]] for x in q(
            "SELECT s.name FROM symptoms s "
            "JOIN disease_symptoms ds ON s.id = ds.symptom_id "
            "WHERE ds.disease_id = %s ORDER BY s.id", d["id"])])
    # v4.10（P2）：病-院发病率索引（罕见判定与样本加权用）
    idmap = {d["name"]: d["id"] for d in diseases}
    rate_lu = {}
    for _r in q("SELECT disease_id, hospital_id, rate FROM prevalence_rates"):
        rate_lu[(_r["disease_id"], _r["hospital_id"])] = float(_r["rate"])

    def synth(rng_, prior, n):
        X, Y = [], []
        for _ in range(n):
            y = int(rng_.choice(D, p=prior))
            pool = dsyms[y]
            k = int(rng_.randint(1, len(pool) + 1))
            chosen = list(rng_.choice(pool, size=k, replace=False))
            if rng_.rand() < 0.15:
                extra = int(rng_.randint(0, S))
                if extra not in chosen:
                    chosen.append(extra)
            x = _fnp.zeros(S)
            for c in chosen:
                x[c] = 1.0
            X.append(x)
            Y.append(y)
        return _fnp.array(X), _fnp.array(Y)

    cases = {}
    holdout = {}
    fb_counts = {}
    fb_boost = {}   # v4.10（P2）：各院被加权的罕见反馈样本数
    agg_ns = {}     # v4.10（P2）：各院唯一参训样本数（聚合权重口径）
    for hi, (hid, hname, n) in enumerate(_FL_SPECS):
        prior = _fnp.ones(D)
        prior[(hi * 2) % D] *= 3.2
        prior[(hi * 2 + 3) % D] *= 2.4
        prior = prior / prior.sum()
        X, Y = synth(rng, prior, n)
        # 本院反馈样本（数据不出院：直接进入本地训练集）
        # v4.10（P2）：罕见病反馈样本按 _RARE_BOOST_K 倍复制（代价敏感学习），
        #   对冲个例被统计平均稀释；聚合权重仍按唯一样本数（agg_ns）计。
        fbx, fby = [], []
        fb_uniq = 0
        for item in _FEEDBACK.get(hid, []):
            yi = nidx.get(item.get("disease"))
            if yi is None:
                continue
            x = _fnp.zeros(S)
            got = False
            if isinstance(item.get("symptoms"), list):
                for s in item["symptoms"]:
                    j = sidx.get(s)
                    if j is not None:
                        x[j] = 1.0
                        got = True
            if got:
                fb_uniq += 1
                _rid = idmap.get(item.get("disease"))
                _rr = rate_lu.get((_rid, hid)) if _rid is not None else None
                _k = 1
                if _RARE_BOOST_K > 1 and _rr is not None and _rr < _RARE_RATE:
                    _k = _RARE_BOOST_K
                    fb_boost[hid] = fb_boost.get(hid, 0) + 1
                for _ in range(_k):
                    fbx.append(x)
                    fby.append(yi)
        if fbx:
            X = _fnp.vstack([X, _fnp.array(fbx)])
            Y = _fnp.concatenate([Y, _fnp.array(fby)])
        fb_counts[hid] = fb_uniq
        agg_ns[hid] = n + fb_uniq
        cases[hid] = (X, Y)
        # 留出集（独立种子，仅评估用）
        n_hold = max(25, int(n * 0.25))
        holdout[hid] = synth(rng_h, prior, n_hold)
    return names, syms, dsyms, cases, holdout, fb_counts, fb_boost, agg_ns

def _dp_epsilon(sigma, delta=_DP_DELTA, rounds=1, compose=True):
    """差分隐私预算估计（演示级口径，诚实标注边界）。

    机制：对「参数更新量 Δ」按阈值 C 裁剪（灵敏度上界 Δf = max_i(n_i/N)·C），
          再加高斯噪声 N(0, (σ·Δf)²) ⇒ 单轮 ε = sqrt(2·ln(1.25/δ)) / σ。

    多轮（可选）：按**基本组合定理**（basic composition）给出最坏情况总预算
          ε_total = T · ε_single。
    注意（重要）：
      · 这是教学演示用的**估计**，不是严格 DP 会计（未用 RDP/矩会计等紧致方法）；
      · 基本组合是**保守（偏大）**的多轮上界；而单轮值若直接当作总预算使用则是**乐观（偏小）**的，
        因此接口同时返回两者，并由前端分别标注。
    """
    import math as _m
    if not sigma or sigma <= 0:
        return {"single": None, "total": None, "rounds": int(rounds),
                "note": "σ=0 即无噪声，无隐私保证"}
    try:
        e1 = float(_m.sqrt(2.0 * _m.log(1.25 / float(delta))) / float(sigma))
    except Exception:
        return {"single": None, "total": None, "rounds": int(rounds), "note": "计算失败"}
    total = e1 * float(rounds) if compose else None
    return {"single": round(e1, 3), "total": (round(total, 3) if total is not None else None),
            "rounds": int(rounds),
            "note": "single=单轮估计；total=T 轮基本组合（保守上界）"}


def _fed_run(rounds=15, sigma=0.0, clip=_DP_CLIP, dp_seed=None):
    """真实 FedAvg：六院本地训练多分类诊断评分模型 → 按样本量加权聚合；含留出集评估。

    v4.9：加入差分隐私（DP-SGD 风格）——sigma > 0 时，
        每院上传前先按 clip 裁剪参数更新，再叠加高斯噪声 N(0, (sigma*clip)^2)，
        实现「连参数也不精确出院」；sigma = 0 即原始 FedAvg（对照基线）。
    """
    import numpy as _fnp
    _dprng = _fnp.random.RandomState(int(dp_seed) if dp_seed is not None else 20261012)
    _dp_on = bool(sigma and sigma > 0)
    _dp_clip_req = float(clip)
    _dp_clip = float(clip)          # 实际生效的裁剪阈值（自适应后可覆盖）
    _dp_sigma = float(sigma)
    _dp_calib = False               # 是否已按首轮更新范数标定阈值
    _dp_noise_scale = None          # 实际使用的噪声标准差（聚合灵敏度 × σ）
    _w_max = max(nn for _, _, nn in _FL_SPECS) / max(1.0, float(sum(nn for _, _, nn in _FL_SPECS)))
    _sens = None                    # 实际使用的灵敏度（w_max × C）
    names, syms, dsyms, cases, holdout, fb_counts, fb_boost, agg_ns = _fed_dataset()
    D = len(names)
    S = len(syms)
    X_all = _fnp.vstack([cases[h][0] for h, _, _ in _FL_SPECS])
    Y_all = _fnp.concatenate([cases[h][1] for h, _, _ in _FL_SPECS])
    Xh = _fnp.vstack([holdout[h][0] for h, _, _ in _FL_SPECS])
    Yh = _fnp.concatenate([holdout[h][1] for h, _, _ in _FL_SPECS])

    def softmax(Wm, b, X):
        z = X @ Wm.T + b
        z = z - z.max(axis=1, keepdims=True)
        p = _fnp.exp(z)
        return p / p.sum(axis=1, keepdims=True)

    def pooled_eval(Wm, b):
        p = softmax(Wm, b, X_all)
        loss = float(-_fnp.mean(_fnp.log(p[_fnp.arange(len(Y_all)), Y_all] + 1e-12)))
        acc = float(_fnp.mean(p.argmax(axis=1) == Y_all))
        return round(loss, 4), round(acc * 100, 1)

    def holdout_eval(Wm, b):
        p = softmax(Wm, b, Xh)
        pred = p.argmax(axis=1)
        loss = float(-_fnp.mean(_fnp.log(p[_fnp.arange(len(Yh)), Yh] + 1e-12)))
        acc = float(_fnp.mean(pred == Yh))
        conf = [[0] * D for _ in range(D)]
        for t, pr in zip(Yh, pred):
            conf[int(t)][int(pr)] += 1
        per = []
        for j in range(D):
            tp = conf[j][j]
            fp = sum(conf[i][j] for i in range(D)) - tp
            fn = sum(conf[j]) - tp
            prec = tp / (tp + fp) if (tp + fp) else 0.0
            rec = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
            per.append({"name": names[j], "support": int(sum(conf[j])),
                        "precision": round(prec * 100, 1), "recall": round(rec * 100, 1), "f1": round(f1 * 100, 1)})
        return {"n": int(len(Yh)), "loss": round(loss, 4), "acc": round(acc * 100, 1),
                "confusion": conf, "per_class": per}

    def local_fit(Wm, b, X, Y, epochs, lr):
        Wm = Wm.copy()
        b = b.copy()
        n = len(X)
        for _ in range(epochs):
            z = X @ Wm.T + b
            z = z - z.max(axis=1, keepdims=True)
            p = _fnp.exp(z)
            p = p / p.sum(axis=1, keepdims=True)
            p[_fnp.arange(n), Y] -= 1.0
            Wm -= lr * (p.T @ X) / n
            b -= lr * p.mean(axis=0)
        return Wm, b

    W = _fnp.zeros((D, S))
    b = _fnp.zeros(D)
    loss0, acc0 = pooled_eval(W, b)
    history = [{"r": 0, "loss": loss0, "acc": acc0}]
    for r in range(1, rounds + 1):
        Ws, bs, ns = [], [], []
        for hid, hname, n in _FL_SPECS:
            X, Y = cases[hid]
            Wl, bl = local_fit(W, b, X, Y, _FL_EPOCHS, _FL_LR)
            Ws.append(Wl)
            bs.append(bl)
            ns.append(agg_ns.get(hid, len(Y)))   # v4.10（P2）：聚合权重按唯一样本数（不含加权复制）
        tot = float(sum(ns))
        # 各院相对全局模型的「参数更新量」
        dWs = [wl - W for wl in Ws]
        dbs = [bl - b for bl in bs]
        if _dp_on and not _dp_calib:
            # 自适应裁剪阈值：首轮各院更新范数的中位数（DP 常见做法，避免手工设定绝对阈值）
            import statistics as _st
            _norms = [float(_fnp.linalg.norm(_dw)) for _dw in dWs]
            _dp_clip = max(1e-6, float(_st.median(_norms)))
            _dp_calib = True
        if _dp_on:
            # ① 逐院裁剪：限制任一医院的更新量贡献（个体影响上界 C）
            def _clip_dp(_d):
                _nrm = float(_fnp.linalg.norm(_d))
                if _nrm > _dp_clip > 0:
                    return _d * (_dp_clip / _nrm)
                return _d
            dWs = [_clip_dp(_dw) for _dw in dWs]
            dbs = [_clip_dp(_db) for _db in dbs]
        aggW = sum(_dw * (nn / tot) for _dw, nn in zip(dWs, ns))
        aggb = sum(_db * (nn / tot) for _db, nn in zip(dbs, ns))
        if _dp_on:
            # ② 高斯机制：噪声标准差 = σ × 聚合灵敏度。
            #    聚合为样本加权平均 Σ(n_i/N)·Δ_i，单院最大权重 w_max = max_i(n_i/N)，
            #    故灵敏度上界 Δf = w_max · C（裁剪保证 ‖Δ_i‖ ≤ C）。
            _w_max = max(nn for _, _, nn in _FL_SPECS) / max(1.0, float(sum(nn for _, _, nn in _FL_SPECS)))
            _sens = _w_max * _dp_clip
            _dp_noise_scale = _dp_sigma * _sens
            aggW = aggW + _dprng.normal(0.0, _dp_noise_scale, aggW.shape)
            aggb = aggb + _dprng.normal(0.0, _dp_noise_scale, aggb.shape)
        W = W + aggW
        b = b + aggb
        loss, acc = pooled_eval(W, b)
        history.append({"r": r, "loss": loss, "acc": acc})

    solo = []
    for hid, hname, n in _FL_SPECS:
        X, Y = cases[hid]
        Wl, bl = local_fit(_fnp.zeros((D, S)), _fnp.zeros(D), X, Y, _FL_SOLO_EPOCHS, _FL_LR)
        l2, a2 = pooled_eval(Wl, bl)
        # v4.10（P1）：本院单干在「本院患者留出集」上的分类表现（聚合控制台·补短板对照）
        Xh_h, Yh_h = holdout[hid]
        ph2 = softmax(Wl, bl, Xh_h)
        pred_h = ph2.argmax(axis=1)
        conf_h = [[0] * D for _ in range(D)]
        for _t, _pr in zip(Yh_h, pred_h):
            conf_h[int(_t)][int(_pr)] += 1
        per_h = []
        for _j in range(D):
            _tp = conf_h[_j][_j]
            _fp = sum(conf_h[_i][_j] for _i in range(D)) - _tp
            _fn = sum(conf_h[_j]) - _tp
            _prc = _tp / (_tp + _fp) if (_tp + _fp) else 0.0
            _rc = _tp / (_tp + _fn) if (_tp + _fn) else 0.0
            _f1 = (2 * _prc * _rc / (_prc + _rc)) if (_prc + _rc) else 0.0
            per_h.append({"name": names[_j], "support": int(sum(conf_h[_j])),
                          "precision": round(_prc * 100, 1), "recall": round(_rc * 100, 1),
                          "f1": round(_f1 * 100, 1)})
        own_acc = float(_fnp.mean(pred_h == Yh_h))
        solo.append({"id": hid, "name": hname, "n": agg_ns.get(hid, len(Y)), "loss": l2, "acc": a2,
                     "own_holdout": {"n": int(len(Yh_h)), "acc": round(own_acc * 100, 1), "per_class": per_h}})

    # 导出可解释权重（症状重要度，按病种归一）；参数 = Σ症状权重 + 病种偏置
    weights = {}
    n_params = 0
    for j, nm in enumerate(names):
        vals = []
        for i in dsyms[j]:
            vals.append(max(0.2, float(W[j][i])))
        mu = sum(vals) / max(len(vals), 1)
        weights[nm] = {syms[i]: round(v / mu, 3) for i, v in zip(dsyms[j], vals)}
        n_params += len(dsyms[j])
    n_params += D
    final = history[-1]
    best_solo = min(solo, key=lambda x: x["loss"])
    ev = holdout_eval(W, b)
    return {
        "ok": True,
        "rounds": rounds,
        "total_samples": int(len(Y_all)),
        "synthetic_samples": sum(s[2] for s in _FL_SPECS),
        "feedback_counts": fb_counts,
        "feedback_boosted": fb_boost,
        "unique_samples": int(sum(agg_ns.values())),
        "weights_used": {h: round(agg_ns[h] / max(1.0, float(sum(agg_ns.values()))), 4) for h in _FL_HIDS},
        "feedback_since": {h: _FB_SINCE.get(h, 0) for h in _FL_HIDS},
        "history": history,
        "solo": solo,
        "final": final,
        "global": {"loss": final["loss"], "acc": final["acc"]},
        "best_solo": {"name": best_solo["name"], "loss": best_solo["loss"], "acc": best_solo["acc"]},
        "holdout": ev,
        "params": n_params,
        "weights": weights,
        "note": "真实 FedAvg · 合成模拟数据（非真实患者数据）+ 本院反馈样本 · 训练完成后全局模型自动供诊断引擎调用",
        "dp": ({"enabled": True, "sigma": round(_dp_sigma, 4),
                "clip_threshold": round(_dp_clip, 6),
                "clip_rule": "首轮各院更新范数的中位数（自适应）",
                "weight_max": round(_w_max, 6),
                "noise_std": (round(_dp_noise_scale, 6) if _dp_noise_scale else None),
                "sensitivity": (round(_sens, 6) if _dp_noise_scale else None),
                "delta": _DP_DELTA,
                "epsilon": _dp_epsilon(_dp_sigma, rounds=rounds),
                "theoretical_note": "演示级估计：单轮为高斯机制公式；多轮为基本组合（保守上界），非严格 DP 会计"}
               if _dp_on else {"enabled": False, "sigma": 0.0}),
    }

def _restore_last():
    global _FL_LAST
    try:
        if os.path.exists(_FL_LAST_FILE):
            with open(_FL_LAST_FILE, encoding="utf-8") as f:
                _FL_LAST = _fjson.load(f)
            print("[联邦能力层] 已恢复最近训练结果（%s 轮）" % _FL_LAST.get("rounds", ""))
    except Exception as e:
        print("[联邦能力层] 训练结果恢复失败：%s" % e)

# ============================================================
# v4.5 新能力：病例反馈数据泵 / 拍照联邦统计 / 训练材料导出
# ============================================================
_FEEDBACK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "feedback.json")
_PHOTO_STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "photo_stats.json")

_FEEDBACK = {h: [] for h in _FL_HIDS}
_FB_SINCE = {h: 0 for h in _FL_HIDS}
_PHOTO_STATS = {h: {"wound": {}, "insect": {}, "level": {}, "total": 0} for h in _FL_HIDS}
_K_ANON = 3

# ── 飞书通知（v4.6）：数据采样 / 训练痕迹推送（异常只记日志，不影响主流程）──
try:
    import feishu_notify as _feishu
except Exception as _feishu_err:
    _feishu = None
    print("[飞书] 通知模块加载失败：%s" % _feishu_err)


def _atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _fjson.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _load_aux():
    try:
        if os.path.exists(_FEEDBACK_FILE):
            with open(_FEEDBACK_FILE, encoding="utf-8") as f:
                blob = _fjson.load(f)
            for h in _FL_HIDS:
                _FEEDBACK[h] = (blob.get(h) or []) + _FEEDBACK.get(h, [])
            # v4.9.3（N5）：恢复「上次训练以来新增」计数；旧数据无 _since 时按 累计-上次训练用量 推导
            _sb = blob.get("_since")
            if not isinstance(_sb, dict):
                _used = ((_FL_LAST or {}).get("feedback_counts") or {})
                _sb = {h: max(0, len(_FEEDBACK.get(h, [])) - int(_used.get(h, 0) or 0)) for h in _FL_HIDS}
            for h in _FL_HIDS:
                _FB_SINCE[h] = int(_sb.get(h, 0) or 0)
            print("[v4.5] 已加载本地反馈样本：%s（训练以来新增：%s）" % (
                {h: len(_FEEDBACK[h]) for h in _FL_HIDS}, dict(_FB_SINCE)))
    except Exception as e:
        print("[v4.5] 反馈样本加载失败：%s" % e)
    try:
        if os.path.exists(_PHOTO_STATS_FILE):
            with open(_PHOTO_STATS_FILE, encoding="utf-8") as f:
                blob2 = _fjson.load(f)
            for h in _FL_HIDS:
                if isinstance(blob2.get(h), dict):
                    for k in _PHOTO_STATS[h]:
                        if k != "total" and isinstance(blob2[h].get(k), dict):
                            _PHOTO_STATS[h][k].update(blob2[h][k])
                        elif k == "total":
                            _PHOTO_STATS[h]["total"] = int(blob2[h].get("total", 0))
            print("[v4.5] 已加载区域伤情统计")
    except Exception as e:
        print("[v4.5] 伤情统计加载失败：%s" % e)


def _save_aux():
    try:
        os.makedirs(os.path.dirname(_FEEDBACK_FILE), exist_ok=True)
        # v4.9.3（N5）：连同「上次训练以来新增」计数一起落盘（_since 键与各院样本同文件）
        _atomic_write(_FEEDBACK_FILE, dict(_FEEDBACK, **{"_since": dict(_FB_SINCE)}))
        _atomic_write(_PHOTO_STATS_FILE, _PHOTO_STATS)
    except Exception as e:
        print("[v4.5] 反馈/统计保存失败：%s" % e)


def _photo_count(acc, rules):
    hid = acc.get("hospital")
    if hid not in _PHOTO_STATS:
        return None
    st = _PHOTO_STATS[hid]
    st["total"] += 1
    w = (rules.get("mapped") or {}).get("wound")
    if w:
        st["wound"][w] = st["wound"].get(w, 0) + 1
    for ins in (rules.get("mapped") or {}).get("insects") or []:
        st["insect"][ins] = st["insect"].get(ins, 0) + 1
    lv = rules.get("level")
    if lv:
        st["level"][lv] = st["level"].get(lv, 0) + 1
    _save_aux()
    return hid


@app.route("/api/feedback", methods=["POST", "OPTIONS"])
def api_feedback():
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    if acc.get("center"):
        return jsonify({"ok": False, "error": "联邦中心账号不产生本地病例样本"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须为 JSON 对象"}), 400
    raw = data.get("symptoms", [])
    if not isinstance(raw, list):
        return jsonify({"ok": False, "error": "symptoms 必须为字符串数组"}), 400
    symptoms = []
    for s in raw:
        if isinstance(s, str):
            s = s.strip()
            if s and s not in symptoms:
                symptoms.append(s)
    disease = data.get("disease")
    action = data.get("action") or "adopt"
    if not symptoms or not isinstance(disease, str) or not disease.strip():
        return jsonify({"ok": False, "error": "缺少症状或疾病名"}), 400
    if action not in ("adopt", "correct"):
        return jsonify({"ok": False, "error": "action 仅支持 adopt / correct"}), 400
    hit = q("SELECT id FROM diseases WHERE name=%s", disease.strip())
    if not hit:
        return jsonify({"ok": False, "error": "未知疾病名"}), 400
    hid = acc["hospital"]
    item = {"symptoms": symptoms, "disease": disease.strip(), "action": action, "ts": int(_time.time())}
    _FEEDBACK.setdefault(hid, []).append(item)
    if len(_FEEDBACK[hid]) > 500:
        _FEEDBACK[hid] = _FEEDBACK[hid][-500:]
    _FB_SINCE[hid] = _FB_SINCE.get(hid, 0) + 1
    _save_aux()
    try:
        _patient_add_record(acc["username"], {
            "date": _ftime.strftime("%Y-%m-%d"), "dept": "线上服务",
            "hospital": acc.get("hospital") or "",
            "title": ("采纳诊断 · " if action == "adopt" else "修正诊断 · ") + disease.strip(),
            "detail": "症状：" + "、".join(symptoms[:8]) + "；结论：" + disease.strip(),
        })
    except Exception as _pe:
        print("[v4.8] 档案写入失败：%s" % _pe)
    if _feishu:
        _feishu.notify_feedback(acc, item, len(_FEEDBACK[hid]))
    return jsonify({"ok": True, "hospital": hid, "stored": len(_FEEDBACK[hid]),
                    "note": "已沉淀为本地训练样本（数据不出院）"})


@app.route("/api/feedback/summary")
def api_feedback_summary():
    acc = _sess(request)
    if not acc:
        return _deny()
    return jsonify({
        "ok": True,
        "cumulative": {h: len(_FEEDBACK.get(h, [])) for h in _FL_HIDS},
        "since_last_train": dict(_FB_SINCE),
        "total": sum(len(_FEEDBACK.get(h, [])) for h in _FL_HIDS),
    })


@app.route("/api/feedback/synthesize", methods=["POST", "OPTIONS"])
def api_feedback_synthesize():
    """v4.10（P3·投喂台）：一键生成本院演示样本（合成，非真实病例）。
    用于演示「本院样本越多 → 聚合权重越大 → 全局模型变化越明显」的因果链；
    focus 可指定病种（如罕见病肺结核），症状从知识库核心症状中按 60%–100% 抽取。"""
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    if acc.get("center"):
        return jsonify({"ok": False, "error": "联邦中心账号不产生本地病例样本"}), 400
    hid = acc.get("hospital")
    if hid not in _FL_HIDS:
        return jsonify({"ok": False, "error": "无效院区"}), 400
    data = request.get_json(silent=True) or {}
    try:
        n = int(data.get("n") or 10)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(50, n))
    focus = str(data.get("focus") or "").strip()
    omit = str(data.get("omit") or "").strip()   # 不典型表现：系统性地少的那个核心症状
    pool = {}
    for _r in q("SELECT d.name AS dn, s.name AS sn FROM disease_symptoms ds "
                "JOIN diseases d ON d.id = ds.disease_id "
                "JOIN symptoms s ON s.id = ds.symptom_id"):
        pool.setdefault(_r["dn"], []).append(_r["sn"])
    if not pool:
        return jsonify({"ok": False, "error": "知识库为空，无法生成样本"}), 500
    # v4.10 复核修复（F3）：focus/omit 无效值显式报错（不再静默回退——
    # 否则调用方以为生成了定向不典型样本，探针对比演示会隐性失效）
    if focus and focus not in pool:
        return jsonify({"ok": False, "error": "未知病种：%s（focus 需为知识库内的病名）" % focus}), 400
    if omit and not focus:
        return jsonify({"ok": False, "error": "omit 需与 focus 同用（指定病种的不典型表现）"}), 400
    if focus and omit:
        _fsyms = pool.get(focus) or []
        if omit not in _fsyms or len(_fsyms) < 3:
            return jsonify({"ok": False, "error": "症状「%s」不在「%s」的核心症状中（或其核心症状不足 3 个），无法生成该不典型表现" % (omit, focus)}), 400
    import random as _rnd
    _rng = _rnd.Random()   # v4.10 复核修复（F2）：系统熵做种子，重复点击不再生成相同样本
    _names = [x for x in pool if pool[x]]
    _added = 0
    for _ in range(n):
        dn = focus if (focus in pool and pool[focus]) else _rng.choice(_names)
        syms = pool[dn]
        if focus and dn == focus and omit and omit in syms and len(syms) >= 3:
            # 定向「不典型表现」样本：核心症状齐全但系统性地缺 omit 那一个
            # （教学意义：让模型学到「该病也可以不表现为某典型症状」，正是特例预警的场景）
            picked = [s for s in syms if s != omit]
        else:
            k = max(2, min(len(syms), int(round(len(syms) * _rng.uniform(0.6, 1.0)))))
            picked = _rng.sample(syms, k)
        _FEEDBACK.setdefault(hid, []).append({
            "symptoms": picked, "disease": dn, "action": "adopt",
            "ts": int(_time.time()), "synthetic": True, "via": "feed-station"})
        _added += 1
    if len(_FEEDBACK[hid]) > 500:
        _FEEDBACK[hid] = _FEEDBACK[hid][-500:]
    _FB_SINCE[hid] = _FB_SINCE.get(hid, 0) + _added
    _save_aux()
    return jsonify({"ok": True, "hospital": hid, "added": _added,
                    "stored": len(_FEEDBACK[hid]),
                    "note": "演示用合成样本（非真实病例），已沉淀至本院样本池",
                    "omit": (omit if (focus and omit) else None)})


@app.route("/api/photo/stats")
def api_photo_stats():
    acc = _sess(request)
    if not acc:
        return _deny()

    def masked(counter):
        shown = {k: v for k, v in counter.items() if v >= _K_ANON}
        hidden = sum(1 for v in counter.values() if v < _K_ANON)
        return {"shown": shown, "hidden_categories": hidden, "k": _K_ANON}

    if acc.get("center"):
        rows = []
        agg = {"wound": {}, "insect": {}, "level": {}}
        for h in _FL_HIDS:
            st = _PHOTO_STATS[h]
            rows.append({"hospital": h, "total": st["total"]})
            for k in agg:
                for name, v in st.get(k, {}).items():
                    agg[k][name] = agg[k].get(name, 0) + v
        return jsonify({"ok": True, "scope": "ALL",
                        "per_hospital": rows,
                        "aggregate": {k: masked(v) for k, v in agg.items()},
                        "total": sum(_PHOTO_STATS[h]["total"] for h in _FL_HIDS)})
    st = _PHOTO_STATS[acc["hospital"]]
    return jsonify({"ok": True, "scope": acc["hospital"], "total": st["total"],
                    "wound": masked(st["wound"]), "insect": masked(st["insect"]), "level": masked(st["level"])})


@app.route("/api/fl/export")
def api_fl_export():
    acc = _sess(request)
    if not acc:
        return _deny()
    blob = {
        "exported_at": _ftime.strftime("%Y-%m-%d %H:%M:%S"),
        "model": dict(_MODEL),
        "last_result": _FL_LAST,
        "feedback": {h: len(_FEEDBACK.get(h, [])) for h in _FL_HIDS},
        "note": "联邦训练日志导出（合成演示数据 + 本地反馈样本）",
    }
    body = _fjson.dumps(blob, ensure_ascii=False, indent=1)
    fn = "fed_training_log_%s.json" % _ftime.strftime("%Y%m%d_%H%M%S")
    return app.response_class(
        body, mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=" + fn})

def _fed_train(rounds=15, notify_acc=None):
    """发起一轮联邦训练：聚合 → 版本 +1 → 下发（持久化）；并结算反馈样本计数"""
    result = _fed_run(rounds)
    global _FL_LAST
    _FL_LAST = result
    _MODEL.update({
        "w": result["weights"],
        "version": _MODEL.get("version", 0) + 1,
        "trained_at": _ftime.strftime("%Y-%m-%d %H:%M:%S"),
        "params": result["params"],
        "rounds": rounds,
        "loss": result["final"]["loss"],
        "acc": result["final"]["acc"],
        "loss_base": result["history"][0]["loss"],
        "holdout_acc": (result.get("holdout") or {}).get("acc"),
        "holdout_n": (result.get("holdout") or {}).get("n"),
        "feedback_total": sum(result.get("feedback_counts", {}).values()),
    })
    _save_model()
    for h in _FL_HIDS:
        _FB_SINCE[h] = 0
    _save_aux()
    print("[联邦能力层] 全局模型 v%s 已下发（损失 %s → %s；留出集准确率 %s%%）" % (
        _MODEL["version"], result["history"][0]["loss"], result["final"]["loss"],
        (result.get("holdout") or {}).get("acc")))
    if _feishu and notify_acc is not None:
        _feishu.notify_train(notify_acc, result, dict(_MODEL))
    return result

@app.route("/api/fl/train", methods=["GET", "POST", "OPTIONS"])
def api_fl_train():
    global _FL_LAST
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    rounds = request.args.get("rounds", 15, type=int)
    rounds = max(1, min(30, rounds))
    if request.method == "POST":
        return jsonify(_fed_train(rounds, notify_acc=acc))
    if _FL_LAST is None:
        _FL_LAST = _fed_train(rounds, notify_acc=acc)
    return jsonify(_FL_LAST)


@app.route("/api/fl/probe")
def api_fl_probe():
    """v4.10（P3·投喂台）：诊断探针——固定症状组合在当前模型下的排名快照。
    投喂前后各调一次，前端对比展示「联邦确实影响了诊断判断」。
    评分口径与 /api/diagnose 完全一致（症状 0.6 + 本院发病率 0.2 + 严重度 0.2）。"""
    acc = _sess(request)
    if not acc:
        return _deny()
    if acc.get("center"):
        return jsonify({"ok": False, "error": "探针请使用医院账号（需本院发病率口径）"}), 400
    hospital_id, err = _resolve_hospital(acc, request.args.get("hospital"))
    if err:
        return err
    W = _MODEL.get("w") or {}
    diseases = q("SELECT * FROM diseases")
    sev_map = {"危急": 1.0, "严重": 0.7, "中度": 0.5, "轻度": 0.3}
    dx_syms = {}
    for _r in q("SELECT ds.disease_id AS did, s.name AS nm FROM disease_symptoms ds "
                "JOIN symptoms s ON s.id = ds.symptom_id"):
        dx_syms.setdefault(_r["did"], []).append(_r["nm"])
    rate_lu = {}
    for _r in q("SELECT disease_id, hospital_id, rate FROM prevalence_rates"):
        rate_lu[(_r["disease_id"], _r["hospital_id"])] = float(_r["rate"])
    probes = []
    for _pb in _V410_PROBES:
        d = next((x for x in diseases if x["name"] == _pb["target"]), None)
        if not d:
            continue
        symptoms = _pb["symptoms"]
        ranked = []
        for dd in diseases:
            ds2 = dx_syms.get(dd["id"], [])
            matched = [s for s in symptoms if s in ds2]
            if not matched:
                continue
            if W and dd["name"] in W:
                wd = W[dd["name"]]
                w_all = {s: float(wd.get(s, 1.0)) for s in ds2}
                sm = min(1.0, sum(w_all.get(s, 1.0) for s in matched) / (sum(w_all.values()) or 1.0))
            else:
                sm = min(1.0, len(matched) / max(len(ds2), 1))
            rate = rate_lu.get((dd["id"], hospital_id), 0.05)
            sv = sev_map.get(dd["severity"], 0.5)
            ranked.append({"name": dd["name"],
                           "score": min(100, round((sm * 0.6 + min(rate * 5, 1) * 0.2 + sv * 0.2) * 100))})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        t_rank = next((i + 1 for i, x in enumerate(ranked) if x["name"] == _pb["target"]), None)
        t_score = next((x["score"] for x in ranked if x["name"] == _pb["target"]), None)
        probes.append({"id": _pb["id"], "target": _pb["target"], "label": _pb["label"],
                       "symptoms": symptoms, "top": ranked[:3],
                       "target_rank": t_rank, "target_score": t_score})
    return jsonify({"ok": True, "hospital": hospital_id,
                    "version": _MODEL.get("version"), "probes": probes})


@app.route("/api/fl/center")
def api_fl_center():
    """v4.10（P1·聚合控制台）：联邦中心专属——参数汇聚 / 聚合下发 / 补短板对照。
    中心不看病、不存病历，只接收各院训练后的参数；本端点汇总联邦的「过程」与「影响」。"""
    acc = _sess(request)
    if not acc:
        return _deny()
    if not acc.get("center"):
        return jsonify({"ok": False, "error": "仅联邦中心账号可访问聚合控制台"}), 403
    ns = _fl_sample_ns()
    tot = float(sum(ns.values())) or 1.0
    gper = {c["name"]: c for c in (((_FL_LAST or {}).get("holdout") or {}).get("per_class") or [])}
    hospitals = []
    for hid, hname, base in _FL_SPECS:
        solo_e = next((s for s in ((_FL_LAST or {}).get("solo") or []) if s.get("id") == hid), None)
        own = (solo_e or {}).get("own_holdout") or {}
        weakest = sorted([c for c in (own.get("per_class") or []) if c.get("support", 0) >= 2],
                         key=lambda c: c["f1"])[:3]
        hospitals.append({
            "id": hid, "name": hname, "samples": ns[hid],
            "weight": round(ns[hid] / tot, 4),
            "solo_acc": (solo_e or {}).get("acc"),
            "own_holdout_acc": own.get("acc"),
            "weakest": [{"name": c["name"], "f1": c["f1"], "recall": c["recall"],
                         "support": c["support"],
                         "federal_f1": (gper.get(c["name"]) or {}).get("f1")} for c in weakest],
        })
    return jsonify({
        "ok": True, "role": "center",
        "global": {"version": _MODEL.get("version"), "acc": _MODEL.get("acc"),
                   "holdout_acc": _MODEL.get("holdout_acc"), "holdout_n": _MODEL.get("holdout_n"),
                   "params": _MODEL.get("params"), "rounds": _MODEL.get("rounds"),
                   "trained_at": _MODEL.get("trained_at"), "loss": _MODEL.get("loss")},
        "hospitals": hospitals,
        "contributions": {h: len(_FEEDBACK.get(h, [])) for h in _FL_HIDS},
        "best_solo": (_FL_LAST or {}).get("best_solo"),
        "note": "中心只接收各院训练后的参数（样本不出院）；聚合权重 = 各院唯一参训样本量占比",
    })


@app.route("/api/fl/dp", methods=["GET", "POST", "OPTIONS"])
def api_fl_dp():
    """v4.9：差分隐私对比实验——同一数据/轮次下，跑多档噪声 σ，返回 精度 vs 隐私预算 曲线。

    只读实验：不写入全局模型、不影响线上诊断（结果单独持久化到 data/fed_dp.json）。
    """
    global _DP_LAST
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    if request.method == "GET" and _DP_LAST is not None and request.args.get("cache") == "1":
        return jsonify(_DP_LAST)
    rounds = request.args.get("rounds", _FL_SUMMARY["rounds_default"], type=int)
    rounds = max(1, min(30, rounds))
    sigmas_raw = request.args.get("sigmas")
    sigmas = _DP_SIGMAS
    if sigmas_raw:
        try:
            sigmas = [max(0.0, float(x)) for x in str(sigmas_raw).split(",")][:6]
        except Exception:
            sigmas = _DP_SIGMAS
    curves = []
    for sg in sigmas:
        r = _fed_run(rounds, sigma=sg, dp_seed=None)
        _dpr = r.get("dp") or {}
        _eps = _dp_epsilon(sg, rounds=rounds) if sg > 0 else {"single": None, "total": None, "rounds": rounds, "note": "无噪声"}
        curves.append({
            "sigma": round(float(sg), 4),
            "epsilon": _eps.get("single"),
            "epsilon_total": _eps.get("total"),
            "rounds": rounds,
            "clip_threshold": _dpr.get("clip_threshold"),
            "sensitivity": _dpr.get("sensitivity"),
            "noise_std": _dpr.get("noise_std"),
            "weight_max": _dpr.get("weight_max"),
            "loss_base": r["history"][0]["loss"],
            "loss": r["final"]["loss"],
            "acc": r["final"]["acc"],
            "holdout_acc": (r.get("holdout") or {}).get("acc"),
            "holdout_n": (r.get("holdout") or {}).get("n"),
            "history": r["history"],
        })
    base = next((c for c in curves if not c["sigma"]), None)
    for c in curves:
        if base and base["acc"] and c["sigma"]:
            c["acc_drop"] = round(float(base["acc"]) - float(c["acc"]), 1)
        elif not c["sigma"]:
            c["acc_drop"] = 0.0
        else:
            c["acc_drop"] = None   # 无基线档时不给数字，避免「零下降」的失真
    _DP_LAST = {
        "ok": True,
        "generated_at": _ftime.strftime("%Y-%m-%d %H:%M:%S"),
        "rounds": rounds,
        "delta": _DP_DELTA,
        "curves": curves,
        "note": ("差分隐私对比（演示级）：对参数更新量按自适应阈值 C 裁剪，再加高斯噪声 "
                 "N(0,(σ·w_max·C)²)，其中 w_max 为最大院样本权重（当前 %.4f）；"
                 "ε_single 为单轮高斯机制估计，ε_total 为 %d 轮基本组合的保守上界；"
                 "非严格 DP 会计；每档均为同数据同轮次的独立实验，不写入全局模型。"
                 % (max(nn for _, _, nn in _FL_SPECS) / max(1.0, float(sum(nn for _, _, nn in _FL_SPECS))), rounds)),
    }
    try:
        _atomic_write(_DP_FILE, _DP_LAST)
    except Exception as _de:
        print("[v4.9] DP 结果保存失败：%s" % _de)
    return jsonify(_DP_LAST)


@app.route("/api/fl/status")
def api_fl_status():
    acc = _sess(request)
    if not acc:
        return _deny()
    return jsonify({
        "ok": True,
        "trained": bool(_MODEL.get("w")),
        "mode": "federated" if _MODEL.get("w") else "baseline",
        "version": _MODEL.get("version", 0),
        "trained_at": _MODEL.get("trained_at"),
        "params": _MODEL.get("params", 0),
        "rounds": _MODEL.get("rounds", 0),
        "loss": _MODEL.get("loss"),
        "loss_base": _MODEL.get("loss_base"),
        "acc": _MODEL.get("acc"),
        "hospitals": len(_FL_SPECS),
        "total_samples": sum(s[2] for s in _FL_SPECS),
        "holdout_acc": _MODEL.get("holdout_acc"),
        "holdout_n": _MODEL.get("holdout_n"),
        "feedback_total": _MODEL.get("feedback_total"),
        "feedback_cumulative": sum(len(_FEEDBACK.get(h, [])) for h in _FL_HIDS),
        "feedback_used_last_train": _MODEL.get("feedback_total"),
        "weights": _fl_weights(),
        "samples_by_hospital": _fl_sample_ns(),
        "hyper": _FL_SUMMARY,
        "dp": ({"clip": _DP_CLIP, "delta": _DP_DELTA, "sigmas": _DP_SIGMAS,
                "last_generated_at": (_DP_LAST or {}).get("generated_at")}),
        "graph_scale": {"diseases": len(q("SELECT id FROM diseases")),
                        "symptoms": len(q("SELECT id FROM symptoms"))},
    })


_load_model()
_restore_last()
_load_aux()
_rusers_load()

def _dp_load():
    """v4.9：加载上次差分隐私对比结果（缺失则忽略）"""
    global _DP_LAST
    try:
        if os.path.exists(_DP_FILE):
            with open(_DP_FILE, encoding="utf-8") as f:
                _DP_LAST = _fjson.load(f)
            print("[v4.9] 已加载差分隐私对比结果（%s）" % (_DP_LAST or {}).get("generated_at"))
    except Exception as e:
        print("[v4.9] DP 结果加载失败：%s" % e)


_dp_load()


# ── 启动 ──


# ============================================================
# AI 聊天接口（百炼大模型 + MySQL 知识库 RAG）
# ============================================================
import requests as _requests

BAILIAN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
BAILIAN_API_KEY = os.environ.get("BAILIAN_KEY", "")
BAILIAN_MODEL = "qwen-plus"
# ── 视觉识别模型（v4.9.1 修复）──
# 背景：阿里云已下线模型名 "qwen-vl-plus"（调用返回 404 Model not exist），
#       导致拍照分析长期走「本地降级」路径、无法描述伤口概况。
# 方案：主用模型可通过环境变量覆盖；同时维护候选列表，逐个尝试并记住首个可用者，
#       避免某个名字再次下线时整个功能失效。
BAILIAN_VL_MODEL = os.environ.get("BAILIAN_VL_MODEL", "qwen3-vl-plus")
_VL_MODEL_CANDIDATES = [
    BAILIAN_VL_MODEL,
    "qwen-vl-ocr",
    "qwen-vl-max-latest",
    "qwen-vl-plus",
]
_VL_MODEL_OK = None   # 首次成功后记住可用模型名，后续直接使用

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


def _chat_context(acc):
    """v4.9：组装问答上下文——病历档案（既往史 / 覆盖医院）+ 最近诊断结论 + 拍照分析历史。

    这是「模块互联」的落地：问答不再只看知识库，而是带上这个人的档案与近期结论。
    返回 (context_text, meta)。
    """
    meta = {"bound": False, "diagnoses": 0, "photos": 0, "hospitals": 0}
    lines = []
    try:
        p = _v48_patient_of(acc.get("username"))
    except Exception:
        p = None
    if p:
        pub = _v48_patient_public(p)
        hist = pub.get("history") or []
        covered = [h for h in (pub.get("hospitals") or []) if h.get("count")]
        age = None
        try:
            if pub.get("birth_year"):
                age = int(_ftime.strftime("%Y")) - int(pub["birth_year"])
        except Exception:
            age = None
        meta.update({"bound": True, "hospitals": len(covered)})
        who = "【患者档案】%s%s%s" % (
            pub.get("name") or "当前用户",
            ("，%s" % pub.get("sex")) if pub.get("sex") else "",
            ("，%d 岁" % age) if age else "")
        tgs = "、".join(pub.get("tags") or [])
        lines.append(who + ("（既往标签：%s）" % tgs if tgs else ""))
        if covered:
            lines.append("【跨院就诊】" + "；".join(
                ["%s %d 条（最近 %s）" % (h.get("name"), h.get("count"), h.get("last") or "—") for h in covered]))
        else:
            lines.append("【跨院就诊】暂无已记录就诊（档案已建立）")
        dx = [h for h in hist if str(h.get("title") or "").startswith(("采纳诊断", "修正诊断"))]
        ph = [h for h in hist if str(h.get("title") or "").startswith("拍照分析")]
        meta["diagnoses"] = len(dx)
        meta["photos"] = len(ph)
        for h in dx[-3:][::-1]:
            lines.append("【历史诊断结论】%s %s：%s" % (h.get("date") or "", h.get("title") or "",
                                                        (h.get("detail") or "")[:100]))
        for h in ph[-2:][::-1]:
            lines.append("【历史拍照分析】%s %s" % (h.get("date") or "", h.get("title") or ""))
    else:
        lines.append("【患者档案】未绑定（如需结合既往病史回答，可先在「病历档案」核验并认领）")
    # 个人拍照历史（未落档案的那部分也带上，保证上下文完整）
    try:
        u_items = [x for x in (_PHOTOHIST.get("items") or []) if x.get("user") == acc.get("username")]
        if u_items:
            meta["photos"] = max(meta["photos"], len(u_items))
            if not any("历史拍照分析" in x for x in lines):
                for it in u_items[-2:][::-1]:
                    lines.append("【历史拍照分析】%s %s（%s）" % (it.get("time") or "", it.get("top") or "",
                                                                 it.get("level") or ""))
    except Exception:
        pass
    return ("\n".join(lines), meta)


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def api_chat():
    if request.method == "OPTIONS":
        return ("", 204)

    acc = _sess(request)
    if not acc:
        return _deny()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"reply": "请求体必须为 JSON 对象"}), 400
    q_raw = data.get("message")
    if q_raw is not None and not isinstance(q_raw, str):
        return jsonify({"reply": "message 必须为字符串"}), 400
    question = (q_raw or "").strip()
    h_raw = data.get("history", [])
    if not isinstance(h_raw, list):
        return jsonify({"reply": "history 必须为数组"}), 400
    history = [
        h for h in h_raw
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)
    ][-6:]  # 最近6条消息作为记忆

    if not question:
        return jsonify({"reply": "请输入您的问题"})

    # ① RAG 检索知识库
    knowledge = _retrieve_knowledge(question)

    # ①' v4.9 上下文层：档案 / 既往诊断 / 拍照分析（模块互联）
    context_text, context_meta = _chat_context(acc)

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
    if context_text:
        system_prompt += ("\n【该用户的院内上下文（已授权，数据不出院）】\n" + context_text +
                          "\n（以上为结构化事实，可自然引用；不要编造未列出的就诊记录。）")

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
            if _feishu:
                _feishu.notify_chat(acc, question, bool(knowledge))
            return jsonify({"reply": answer, "knowledge_hit": bool(knowledge),
                            "context_used": bool((context_meta or {}).get("bound")),
                            "context": context_meta,
                            "sources": (["院内知识库"] + (["个人病历档案"] if context_meta.get("bound") else []))})
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

# （v4.8：拍照分析接口已升级——全过程步骤 / 相似病例对比 / 历史记忆 / 自动落档；完整实现见文件尾部「v4.8 病历档案 + 拍照分析升级」章节）



@app.route("/sample/<fn>")
def photo_sample(fn):
    if fn not in ("sample_wound.jpg", "sample_bite.jpg", "sample_scalp.jpg", "sample_arm.jpg"):
        return ("not found", 404)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), fn)
    if not os.path.exists(p):
        return ("not found", 404)
    with open(p, "rb") as f:
        data = f.read()
    return app.response_class(data, mimetype="image/jpeg")


# ============================================================
# v4.8 病历档案 + 拍照分析升级（全过程可见 / 病例对比 / 历史记忆）
# ============================================================
# 说明：
# - 病历档案：data/patients.json（演示合成数据）+ 账号绑定；身份核验 → 认领既往记录
# - 拍照升级：data/photo_cases.json（示范病例库）+ data/photo_history.json（个人历史）
# - 原 /api/photo/analyze 已迁移到本章节（全过程步骤 + 相似病例 + 历史对比 + 自动落档）
import base64 as _b64
import io as _io

try:
    from PIL import Image as _PImg, ImageFilter as _PImgF
except Exception:
    _PImg = None
    _PImgF = None

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PATIENTS_FILE = os.path.join(_BASE_DIR, "data", "patients.json")
_CASES_FILE = os.path.join(_BASE_DIR, "data", "photo_cases.json")
_PHOTOHIST_FILE = os.path.join(_BASE_DIR, "data", "photo_history.json")
_PHOTOS_DIR = os.path.join(_BASE_DIR, "data", "photos")

_PATIENTS = {"note": "", "patients": [], "bindings": {}}
_CASES = {"note": "", "confusions": [], "sample_hints": [], "cases": []}
_PHOTOHIST = {"note": "", "seq": 0, "items": []}
_V48_VL_CACHE = {}


def _v48_load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return _fjson.load(f)
    except Exception as e:
        print("[v4.8] 读取失败 %s：%s" % (os.path.basename(path), e))
    return default


def _patients_load():
    global _PATIENTS
    blob = _v48_load_json(_PATIENTS_FILE, None)
    if isinstance(blob, dict):
        blob.setdefault("patients", [])
        blob.setdefault("bindings", {})
        _PATIENTS = blob
        print("[v4.8] 已加载病历档案：%d 份（已绑定 %d 个账号）" % (len(_PATIENTS["patients"]), len(_PATIENTS["bindings"])))


def _patients_save():
    try:
        _atomic_write(_PATIENTS_FILE, _PATIENTS)
    except Exception as e:
        print("[v4.8] 档案保存失败：%s" % e)


def _cases_load():
    global _CASES
    blob = _v48_load_json(_CASES_FILE, None)
    if isinstance(blob, dict):
        blob.setdefault("cases", [])
        blob.setdefault("confusions", [])
        blob.setdefault("sample_hints", [])
        _CASES = blob
        print("[v4.8] 已加载示范病例库：%d 例" % len(_CASES["cases"]))


def _photohist_load():
    global _PHOTOHIST
    blob = _v48_load_json(_PHOTOHIST_FILE, None)
    if isinstance(blob, dict):
        blob.setdefault("items", [])
        blob.setdefault("seq", 0)
        _PHOTOHIST = blob


def _photohist_save():
    try:
        _atomic_write(_PHOTOHIST_FILE, _PHOTOHIST)
    except Exception as e:
        print("[v4.8] 拍照历史保存失败：%s" % e)


def _v48_patient_of(user):
    pid = (_PATIENTS.get("bindings") or {}).get(user or "")
    if not pid:
        return None
    for p in _PATIENTS.get("patients", []):
        if p.get("pid") == pid:
            return p
    return None


def _v48_mask_phone(ph):
    s = str(ph or "")
    if len(s) >= 11:
        return s[:3] + "****" + s[-4:]
    return s


def _v48_patient_public(p):
    hist = list(p.get("history") or [])
    hospitals = []
    for hid, hname, _n in _FL_SPECS:
        recs = [h for h in hist if (h.get("hospital") or "") == hid]
        last = ""
        for h in recs:
            d = str(h.get("date") or "")
            if d > last:
                last = d
        hospitals.append({"id": hid, "name": hname, "count": len(recs), "last": last})
    return {
        "pid": p.get("pid"), "name": p.get("name"), "sex": p.get("sex"),
        "birth_year": p.get("birth_year"), "phone": _v48_mask_phone(p.get("phone")),
        "tags": p.get("tags") or [], "created": p.get("created"),
        "history": hist, "hospitals": hospitals,
    }


def _patient_add_record(user, rec):
    """向当前账号绑定档案追加一条记录（诊断采纳 / 拍照分析等）。返回是否成功。"""
    p = _v48_patient_of(user)
    if not p:
        return False
    rec = dict(rec)
    rec.setdefault("date", _ftime.strftime("%Y-%m-%d"))
    hist = p.setdefault("history", [])
    hist.append(rec)
    if len(hist) > 80:
        del hist[0:len(hist) - 80]
    _patients_save()
    return True


# ---------- 图片工具（演示级近似指标） ----------

def _v48_b64_image(img_data_url):
    try:
        head, _, b64 = img_data_url.partition(",")
        raw = _b64.b64decode(b64)
        low = head.lower()
        ext = "jpg"
        if "png" in low:
            ext = "png"
        elif "webp" in low:
            ext = "webp"
        return raw, ext, None
    except Exception as e:
        return None, None, str(e)[:120]


def _v48_metrics(raw):
    if _PImg is None:
        return None
    try:
        im = _PImg.open(_io.BytesIO(raw)).convert("RGB")
    except Exception:
        return None
    w, h = im.size
    sample = im
    if max(w, h) > 480:
        k = 480.0 / max(w, h)
        sample = im.resize((max(1, int(w * k)), max(1, int(h * k))), _PImg.LANCZOS)
    px = sample.load()
    sw, sh = sample.size
    n = max(1, sw * sh)
    tot = 0
    red = 0
    sumr = sumg = sumb = 0
    for y in range(sh):
        for x in range(sw):
            r, g, b = px[x, y]
            sumr += r; sumg += g; sumb += b
            tot += (r * 299 + g * 587 + b * 114) // 1000
            if r - max(g, b) > 22:
                red += 1
    edge = 0
    try:
        gray = sample.convert("L").filter(_PImgF.FIND_EDGES)
        ep = gray.load()
        se = 0
        for y in range(1, sh - 1):
            for x in range(1, sw - 1):
                se += ep[x, y]
        edge = se // max(1, (sw - 2) * (sh - 2))
    except Exception:
        edge = 0
    return {
        "w": w, "h": h,
        "brightness": int(tot // n),
        "redness": round(red * 100.0 / n, 1),
        "edge": int(edge),
        "avg": [int(sumr // n), int(sumg // n), int(sumb // n)],
    }


def _v48_quality(metrics, kb):
    q = []
    lvl = "良好"
    if metrics:
        b = metrics["brightness"]
        if b < 60:
            q.append("照片偏暗，建议在光线充足处重拍")
            lvl = "一般"
        elif b > 205:
            q.append("照片偏亮 / 过曝，细节可能丢失")
            lvl = "一般"
        else:
            q.append("亮度适中")
        if metrics["edge"] < 6:
            q.append("图像较平滑（可能虚焦或距离过近）")
            lvl = "一般"
        elif metrics["edge"] > 60:
            q.append("纹理丰富（细节清晰）")
        else:
            q.append("清晰度可用")
        if kb > 6000:
            q.append("尺寸较大，已按需压缩处理")
    else:
        q.append("未能解析图像细节（服务未就绪）")
    return {"level": lvl, "items": q}


def _v48_case_match(text, limit=3):
    t = str(text or "")
    scored = []
    for c in _CASES.get("cases", []):
        hits = [tg for tg in (c.get("tags") or []) if tg and (tg in t)]
        if hits:
            scored.append({"id": c.get("id"), "name": c.get("name"), "hits": hits[:6], "score": len(hits), "src": "text"})
    scored.sort(key=lambda x: -x["score"])
    strong = [s for s in scored if s["score"] >= 2]
    return strong[:limit] if strong else scored[:2]


def _v48_sample_hint(mk):
    out = []
    for sh in _CASES.get("sample_hints") or []:
        if sh.get("md5") and sh.get("md5") == mk:
            for cid in (sh.get("cases") or []):
                c = next((x for x in _CASES.get("cases", []) if x.get("id") == cid), None)
                if c:
                    out.append({"id": c["id"], "name": c["name"], "hits": ["示例预置匹配"],
                                "score": 9, "src": "sample", "note": sh.get("note") or ""})
    return out


def _v48_confusion(case_ids):
    ids = set(case_ids or [])
    for cf in _CASES.get("confusions") or []:
        if cf.get("a") in ids and cf.get("b") in ids:
            return cf
    return None


def _v48_case_public(cid):
    c = next((x for x in _CASES.get("cases", []) if x.get("id") == cid), None)
    if not c:
        return None
    return {"id": c.get("id"), "name": c.get("name"), "image": "/static/cases/" + str(c.get("file") or ""),
            "tags": c.get("tags") or [], "features": c.get("features"), "diff": c.get("diff"), "care": c.get("care")}


def _v48_history_compare(user, metrics):
    items = [it for it in _PHOTOHIST.get("items", []) if it.get("user") == user]
    items = sorted(items, key=lambda x: x.get("ts") or 0, reverse=True)
    prev = items[0] if items else None
    if not prev or not metrics:
        return {"prev": None, "deltas": {}, "note": ""}
    pm = prev.get("metrics") or {}
    deltas = {}
    note = []
    try:
        a = float(pm.get("redness") or 0)
        b = float(metrics.get("redness") or 0)
        if a > 0.5:
            d = round((b - a) * 100.0 / a, 1)
            deltas["redness"] = d
            if d <= -12:
                note.append("红色区域较上次减少 %.0f%%（图像指标，疑似好转趋势）" % abs(d))
            elif d >= 12:
                note.append("红色区域较上次增加 %.0f%%，建议留意变化" % d)
            else:
                note.append("红色区域与上次基本相当")
        a2 = float(pm.get("edge") or 0)
        b2 = float(metrics.get("edge") or 0)
        if a2 > 0.5:
            deltas["edge"] = round((b2 - a2) * 100.0 / a2, 1)
    except Exception:
        pass
    if not note:
        note.append("与上次记录的图像指标基本持平")
    return {
        "prev": {"id": prev.get("id"), "time": prev.get("time"), "top": prev.get("top"), "level": prev.get("level")},
        "deltas": deltas,
        "note": "；".join(note) + "（演示级近似，仅供趋势参考）",
    }


def _v48_save_photo(user, raw, ext):
    try:
        d = os.path.join(_PHOTOS_DIR, user)
        os.makedirs(d, exist_ok=True)
        fn = "%s_%s.%s" % (_ftime.strftime("%Y%m%d_%H%M%S"), _uuid.uuid4().hex[:6],
                           ext if ext in ("jpg", "png", "webp") else "jpg")
        with open(os.path.join(d, fn), "wb") as f:
            f.write(raw)
        return user + "/" + fn
    except Exception as e:
        print("[v4.8] 照片保存失败：%s" % e)
        return None


def _v48_add_history(user, raw, ext, top, level, metrics, case_names):
    rel = _v48_save_photo(user, raw, ext)
    if not rel:
        return None
    _PHOTOHIST["seq"] = int(_PHOTOHIST.get("seq") or 0) + 1
    item = {"id": "h%04d" % _PHOTOHIST["seq"], "user": user, "ts": int(_ftime.time()),
            "time": _ftime.strftime("%Y-%m-%d %H:%M"), "top": top, "level": level,
            "cases": case_names, "metrics": metrics, "file": rel}
    items = _PHOTOHIST.setdefault("items", [])
    items.append(item)
    if len(items) > 500:
        _PHOTOHIST["items"] = items[-500:]
    _photohist_save()
    return item


# ---------- 病历档案接口 ----------

@app.route("/api/patient/match", methods=["POST", "OPTIONS"])
def api_patient_match():
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须为 JSON 对象"}), 400
    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    want_h = str(data.get("hospital") or "").strip().upper()
    if not name or not phone:
        return jsonify({"ok": False, "error": "请填写姓名与手机号后进行核验"}), 400
    if len(name) > 20 or len(phone) > 20:
        return jsonify({"ok": False, "error": "输入过长"}), 400
    if want_h and want_h not in _FED_HIDS:
        return jsonify({"ok": False, "error": "未知医院标识（仅支持 A–F）"}), 400
    hit = None
    name_only = False
    for p in _PATIENTS.get("patients", []):
        if p.get("name") == name:
            if p.get("phone") == phone:
                hit = p
                break
            name_only = True
    cur_pid = (_PATIENTS.get("bindings") or {}).get(acc["username"])
    if not hit:
        hint = "姓名存在就诊记录，但手机号不匹配——请核对后重试" if name_only else "未找到匹配档案，可建立新档案"
        return jsonify({"ok": True, "matched": False, "hint": hint, "already_bound": bool(cur_pid)})
    pub = _v48_patient_public(hit)
    resp = {"ok": True, "matched": True, "already_bound": bool(cur_pid), "patient": pub}
    if want_h:
        cnt = len([h2 for h2 in (hit.get("history") or []) if (h2.get("hospital") or "") == want_h])
        resp["scope"] = {"hospital": want_h, "count": cnt}
        if cnt == 0:
            resp["hospital_hint"] = "该院暂无就诊记录——可切换其他医院查看，或先建立新档案。"
    return jsonify(resp)


@app.route("/api/patient/bind", methods=["POST", "OPTIONS"])
def api_patient_bind():
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须为 JSON 对象"}), 400
    pid = str(data.get("pid") or "").strip()
    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    p = next((x for x in _PATIENTS.get("patients", []) if x.get("pid") == pid), None)
    if not p:
        return jsonify({"ok": False, "error": "档案不存在"}), 404
    # v4.9.3（N1）：认领必须复用身份核验——姓名 + 手机号须与档案一致，防止仅凭 pid 枚举认领他人档案
    if not name or not phone or p.get("name") != name or p.get("phone") != phone:
        return jsonify({"ok": False, "error": "身份核验未通过：请先完成姓名与手机号核验，再认领该档案"}), 403
    _PATIENTS.setdefault("bindings", {})[acc["username"]] = pid
    _patients_save()
    return jsonify({"ok": True, "bound": True, "patient": _v48_patient_public(p)})


@app.route("/api/patient/create", methods=["POST", "OPTIONS"])
def api_patient_create():
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须为 JSON 对象"}), 400
    name = str(data.get("name") or "").strip()[:20]
    sex = str(data.get("sex") or "").strip()
    phone = str(data.get("phone") or "").strip()[:20]
    try:
        by = int(data.get("birth_year") or 0)
    except Exception:
        by = 0
    if not name:
        return jsonify({"ok": False, "error": "请填写姓名"}), 400
    if sex not in ("男", "女", "未填"):
        sex = "未填"
    if not (1900 <= by <= 2026):
        by = 0
    seq = 9000
    for x in _PATIENTS.get("patients", []):
        m = _re.match(r"^P(\d+)$", str(x.get("pid") or ""))
        if m:
            seq = max(seq, int(m.group(1)))
    pid = "P%d" % (seq + 1)
    p = {"pid": pid, "name": name, "sex": sex, "birth_year": by, "phone": phone,
         "created": _ftime.strftime("%Y-%m-%d"), "tags": [],
         "history": [{"date": _ftime.strftime("%Y-%m-%d"), "dept": "线上服务",
                      "hospital": acc.get("hospital") or "",
                      "title": "新建档案", "detail": "由用户自助建立的演示档案。"}]}
    _PATIENTS.setdefault("patients", []).append(p)
    _PATIENTS.setdefault("bindings", {})[acc["username"]] = pid
    _patients_save()
    return jsonify({"ok": True, "bound": True, "patient": _v48_patient_public(p)})


@app.route("/api/patient/unbind", methods=["POST", "OPTIONS"])
def api_patient_unbind():
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    (_PATIENTS.get("bindings") or {}).pop(acc["username"], None)
    _patients_save()
    return jsonify({"ok": True, "bound": False})


@app.route("/api/patient/context")
def api_patient_context():
    """v4.9：把「病历档案 / 既往诊断 / 拍照分析」汇总为上下文，供诊断与问答模块引用（模块互联）。

    只读接口，仅返回当前账号绑定的档案；未绑定返回 bound=false。
    """
    acc = _sess(request)
    if not acc:
        return _deny()
    p = _v48_patient_of(acc["username"])
    out = {"ok": True, "bound": False, "patient": None,
           "recent_diagnoses": [], "recent_photos": [],
           "photo_history_count": 0, "hospitals_covered": 0, "note": ""}
    # 拍照历史（个人维度）
    try:
        u_items = [x for x in (_PHOTOHIST.get("items") or []) if x.get("user") == acc["username"]]
        out["photo_history_count"] = len(u_items)
    except Exception:
        u_items = []
    if not p:
        out["note"] = "未绑定病历档案：绑定后可让诊断自动参考既往就诊与历史结论（数据不出院）"
        return jsonify(out)
    pub = _v48_patient_public(p)
    covered = [h for h in (pub.get("hospitals") or []) if h.get("count")]
    age = None
    try:
        if pub.get("birth_year"):
            age = int(_ftime.strftime("%Y")) - int(pub["birth_year"])
    except Exception:
        age = None
    out["bound"] = True
    out["patient"] = {
        "pid": pub.get("pid"), "name": pub.get("name"), "sex": pub.get("sex"),
        "age": age, "tags": pub.get("tags") or [], "created": pub.get("created"),
        "hospitals_covered": len(covered),
        "hospitals": covered,
        "history_count": len(pub.get("history") or []),
    }
    out["hospitals_covered"] = len(covered)
    hist = pub.get("history") or []
    dx = [h for h in hist if str(h.get("title") or "").startswith(("采纳诊断", "修正诊断"))]
    ph = [h for h in hist if str(h.get("title") or "").startswith("拍照分析")]
    out["recent_diagnoses"] = [{"date": h.get("date"), "title": h.get("title"),
                                "detail": (h.get("detail") or "")[:120],
                                "hospital": h.get("hospital")} for h in dx[-5:]][::-1]
    out["recent_photos"] = [{"date": h.get("date"), "title": h.get("title"),
                             "hospital": h.get("hospital")} for h in ph[-5:]][::-1]
    if u_items:
        out["recent_photos_personal"] = [{"time": it.get("time"), "top": it.get("top"),
                                          "level": it.get("level")} for it in u_items[-3:]][::-1]
    out["note"] = ("诊断与问答已自动引用该档案：既往 %d 条记录 · 覆盖 %d 家医院 · 历史结论 %d 条"
                   % (len(hist), len(covered), len(dx)))
    return jsonify(out)


@app.route("/api/patient/me")
def api_patient_me():
    acc = _sess(request)
    if not acc:
        return _deny()
    user = acc["username"]
    items = [it for it in _PHOTOHIST.get("items", []) if it.get("user") == user]
    items = sorted(items, key=lambda x: x.get("ts") or 0, reverse=True)
    photos = [{"id": it.get("id"), "ts": it.get("ts"), "time": it.get("time"), "top": it.get("top"),
               "level": it.get("level"), "metrics": it.get("metrics")} for it in items[:12]]
    p = _v48_patient_of(user)
    if not p:
        return jsonify({"ok": True, "bound": False, "photos": photos, "photo_count": len(items)})
    return jsonify({"ok": True, "bound": True, "patient": _v48_patient_public(p),
                    "photos": photos, "photo_count": len(items)})


# ---------- 病例库 / 历史图片接口 ----------

@app.route("/api/photo/cases")
def api_photo_cases():
    acc = _sess(request)
    if not acc:
        return _deny()
    cases = [_v48_case_public(c.get("id")) for c in _CASES.get("cases", [])]
    cases = [c for c in cases if c]
    return jsonify({"ok": True, "cases": cases, "confusions": _CASES.get("confusions") or [],
                    "note": _CASES.get("note") or ""})


@app.route("/api/photo/image/<iid>")
def api_photo_image(iid):
    acc = _sess(request)
    if not acc:
        return _deny()
    it = next((x for x in _PHOTOHIST.get("items", [])
               if str(x.get("id")) == str(iid) and x.get("user") == acc["username"]), None)
    if not it or not it.get("file"):
        return ("not found", 404)
    p = os.path.normpath(os.path.join(_PHOTOS_DIR, it["file"]))
    if not p.startswith(os.path.normpath(_PHOTOS_DIR)):
        return ("bad request", 400)
    if not os.path.exists(p):
        return ("not found", 404)
    with open(p, "rb") as f:
        data = f.read()
    return app.response_class(data, mimetype="image/jpeg")


# ---------- 拍照分析（v4.8 升级版） ----------

@app.route("/api/photo/analyze", methods=["POST", "OPTIONS"])
def api_photo_analyze():
    global _VL_MODEL_OK
    if request.method == "OPTIONS":
        return ("", 204)
    acc = _sess(request)
    if not acc:
        return _deny()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    img = data.get("image") or ""
    if not (isinstance(img, str) and img.startswith("data:image")):
        return jsonify({"ok": False, "error": "请提供图片（data:image/... base64 格式）"}), 400
    if len(img) > 8000000:
        return jsonify({"ok": False, "error": "图片过大，请压缩后重试（建议小于 5MB）"}), 400
    user = acc["username"]
    raw, ext, err = _v48_b64_image(img)
    if err or not raw:
        return jsonify({"ok": False, "error": "图片解析失败，请重新选择照片"}), 400
    mk = _hashlib.md5(raw).hexdigest()
    kb = int(len(raw) / 1024)

    # ① 图像接收 + 指标
    metrics = _v48_metrics(raw)
    size_txt = ("%d×%d · %d KB" % (metrics["w"], metrics["h"], kb)) if metrics else ("%d KB" % kb)

    # ② 质量检查
    quality = _v48_quality(metrics, kb)

    # ③ 智能识别（在线 VL / 本地降级）
    vl = None
    engine = {"mode": "fallback", "model": None,
              "detail": "云端视觉识别未连接，已降级为本地基础检查（质量检查与病例库仍可用，历史对比不受影响）"}
    if mk in _V48_VL_CACHE:
        vl = _V48_VL_CACHE[mk]
        engine = {"mode": "vl", "model": (_VL_MODEL_OK or BAILIAN_VL_MODEL),
                  "detail": "识别引擎：通义千问 VL（命中缓存 · %s）" % (_VL_MODEL_OK or BAILIAN_VL_MODEL)}
    else:
        prompt = ("这是一张皮肤患处照片。请只输出 JSON（不要其他文字）："
                  '{"condition":"皮肤表现的一句话描述","likely_cause":["若疑似叮咬，列出可能的昆虫来源，最多3个；否则空数组"],'
                  '"confidence":"推断置信度 低/中/高","severity":"轻度/中度/重度",'
                  '"features":["观察到的主要特征（颜色 / 边界 / 鳞屑 / 分布等特点），2-6条"],'
                  '"advice_level":"自行处理/建议就医/尽快就医","red_flags":["需要警惕的情况，0-4条"],"note":"一句话补充"}')
        # v4.9.1：按候选列表逐个尝试视觉模型，成功即记住并复用；
        # 某模型「不存在/无权限」时自动换下一个，全部失败才降级为本地基础检查。
        _cands = ([_VL_MODEL_OK] if _VL_MODEL_OK else []) + \
                 [m for m in _VL_MODEL_CANDIDATES if m != _VL_MODEL_OK]
        _errs = []
        for _vm in _cands:
            try:
                resp = _requests.post(
                    BAILIAN_API_URL,
                    headers={"Authorization": "Bearer " + BAILIAN_API_KEY, "Content-Type": "application/json"},
                    json={"model": _vm, "messages": [{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": img}}]}], "temperature": 0.2},
                    timeout=120,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    vl = _photo_json(content) or {"condition": (content or "")[:120], "features": [], "advice_level": "自行处理"}
                    _V48_VL_CACHE[mk] = vl
                    _VL_MODEL_OK = _vm
                    engine = {"mode": "vl", "model": _vm,
                              "detail": "识别引擎：通义千问 VL（在线 · %s）" % _vm}
                    break
                # 非 200：记录原因后换下一个候选（模型下线时表现为 404）
                _errs.append("%s→HTTP %s" % (_vm, resp.status_code))
            except Exception as e:
                _errs.append("%s→%s" % (_vm, str(e)[:60]))
        if vl is None:
            _tail = "；".join(_errs[-2:]) if _errs else "无可用候选模型"
            engine["detail"] = "云端识别不可用（%s），已降级为本地基础检查" % _tail

    # 规则层（保留原知识库逻辑；降级时补充通用提示）
    if vl is not None:
        rules = _photo_rules(vl)
    else:
        rules = _photo_rules({})
        rules["care"] = ["保持局部清洁，避免抓挠与热水刺激", "观察 48 小时变化；如加重，建议就医评估"]

    # ④ 病例匹配（示例图预置匹配 + 描述特征匹配）
    if vl is not None:
        text_pool = " ".join([str(vl.get("condition") or "")] + [str(x) for x in (vl.get("features") or [])]
                             + [str(x) for x in (vl.get("likely_cause") or [])] + [str(vl.get("note") or "")])
    else:
        text_pool = ""
    seen = set()
    matched = []
    for m0 in _v48_sample_hint(mk) + _v48_case_match(text_pool):
        if m0["id"] in seen:
            continue
        seen.add(m0["id"])
        matched.append(m0)
    matched = matched[:3]
    matched_pub = []
    for m0 in matched:
        cp = _v48_case_public(m0["id"])
        if cp:
            cp["hits"] = m0.get("hits") or []
            cp["score"] = m0.get("score")
            cp["src"] = m0.get("src")
            matched_pub.append(cp)
    confusion = _v48_confusion([m0["id"] for m0 in matched])

    # ⑤ 历史对比（个人记忆）
    hist = _v48_history_compare(user, metrics)
    compare_desc = hist["note"] if hist.get("prev") else "暂无个人历史记录，本次将作为第一条记录存档"
    if confusion:
        compare_desc += "；重点鉴别：" + str(confusion.get("title") or "")

    # ⑥⑦ 常规解读 + 落档
    top_label = matched_pub[0]["name"] if matched_pub else str((vl or {}).get("condition") or "皮肤表现")[:24]
    saved = None
    if metrics is not None:
        saved = _v48_add_history(user, raw, ext, top_label, rules["level"], metrics, [m0["id"] for m0 in matched])
    pat = _v48_patient_of(user)
    if pat is not None and saved is not None:
        try:
            _patient_add_record(user, {"date": _ftime.strftime("%Y-%m-%d"), "dept": "线上服务",
                                       "hospital": acc.get("hospital") or "",
                                       "title": "拍照分析 · " + str(top_label),
                                       "detail": "分析处置建议：%s；结果与图片已存档，可用于后续对比。" % rules["level"]})
        except Exception as _pe:
            print("[v4.8] 档案写入失败：%s" % _pe)

    steps = [
        {"id": "recv", "title": "图像接收", "detail": "已接收照片：" + size_txt + "（" + _ftime.strftime("%H:%M:%S") + "）"},
        {"id": "quality", "title": "质量检查", "detail": "质量评级：" + quality["level"] + " · " + "；".join(quality["items"][:3])},
        {"id": "identify", "title": "智能识别", "detail": engine["detail"]},
        {"id": "match", "title": "病例匹配",
         "detail": ("命中相似示范病例 %d 例：%s" % (len(matched_pub), "、".join([m0["name"] for m0 in matched_pub])))
                   if matched_pub else "未命中高相似病例（可浏览下方示范病例库）"},
        {"id": "compare", "title": "对比分析", "detail": compare_desc},
        {"id": "advice", "title": "常规解读", "detail": "已生成护理建议 / 用药参考 / 就医分级（见下方卡片）"},
        {"id": "save", "title": "结果落档",
         "detail": ("已存入" + (("【" + str(pat.get("name")) + "】的") if pat else "") + "拍照历史" +
                    ("，并关联健康档案" if (pat is not None and saved) else "") + "，后续分析可自动对比")
                   if saved else "图片未存档（图像解析异常）"},
    ]

    result = {
        "ok": True,
        "v48": True,
        "engine": engine,
        "quality": quality,
        "metrics": metrics,
        "steps": steps,
        "cases": {"matched": matched_pub, "confusion": confusion, "total": len(_CASES.get("cases", []))},
        "history": hist,
        "saved": ({"id": saved["id"], "time": saved["time"], "linked_patient": bool(pat)} if saved else None),
        "analysis": vl or {"condition": "本地基础检查（未连接在线识别）", "features": quality["items"][:4],
                           "confidence": "—", "severity": "—", "advice_level": rules["level"], "red_flags": [],
                           "note": "网络恢复后可重新分析获得更完整的识别结果。"},
        "mapped": rules["mapped"], "level": rules["level"], "care": rules["care"], "meds": rules["meds"],
        "red_flags": rules["red_flags"], "insects": rules["insects"], "disclaimer": _PHOTO_DISCLAIMER,
    }
    counted = _photo_count(acc, rules) if vl is not None else None
    if _feishu and vl is not None:
        try:
            _feishu.notify_photo(acc, rules, _PHOTO_STATS.get(counted, {}).get("total", 0) if counted else 0)
        except Exception:
            pass
    result["counted"] = bool(counted)
    result["counted_hospital"] = counted
    return jsonify(result)


# ---------- 启动加载 ----------
_patients_load()
_cases_load()
_photohist_load()


if __name__ == "__main__":
    print("=" * 50)
    print("  联邦医院知识图谱AI — 后端已启动（v4.9 可解释 + 差分隐私版）")
    print("  数据库: %s / %s（可用 .env 的 HG_DB_* 覆盖）" % (DB["host"], DB["database"]))
    print("  百炼 Key: %s" % ("已配置" if BAILIAN_API_KEY else "未配置（问答/拍照识别不可用，其余功能正常）"))
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
    print("    POST /api/login        — 登录（医院演示账号 / 自助注册）")
    print("    POST /api/register     — 用户注册（自助开通）")
    print("    GET  /app              — 应用台（新版界面 · 侧栏导航）")
    print("    POST /api/logout       — 退出登录")
    print("    GET  /api/me           — 会话查询")
    print("    GET  /api/fl/train     — 联邦训练结果（首次自动训练）")
    print("    POST /api/fl/train     — 联邦训练·再训一轮（真实 FedAvg）")
    print("    GET  /api/fl/status    — 联邦全局模型状态")
    print("    GET  /api/fl/export    — 训练日志导出")
    print("    POST /api/feedback     — 病例反馈（本地沉淀）")
    print("    GET  /api/photo/stats  — 区域伤情统计（k-匿名）")
    print("    POST /api/patient/match  — 病历档案·身份核验")
    print("    GET  /api/patient/me     — 我的健康档案（关联病史）")
    print("    GET  /api/photo/cases    — 示范病例库（相似病例对比）")
    print("    GET  /api/graph        — 知识图谱（?scope=local|fed）")
    print("    GET  /legacy           — 旧版页面（保留通道）")
    print("=" * 50)
    _host = os.environ.get("HG_HOST", "127.0.0.1")
    _port = int(os.environ.get("HG_PORT", "5000"))
    _debug = os.environ.get("HG_DEBUG", "1") == "1"
    if _host not in ("127.0.0.1", "localhost") and _debug:
        print("  [安全提示] 已向局域网开放且调试模式开启，建议设置 HG_DEBUG=0")
    if _host == "0.0.0.0":
        try:
            import socket as _sk
            _s = _sk.socket(_sk.AF_INET, _sk.SOCK_DGRAM)
            _s.connect(("10.255.255.255", 1))
            _lan_ip = _s.getsockname()[0]
            _s.close()
            print("  [手机访问] 同一网络下访问: http://%s:%d" % (_lan_ip, _port))
        except Exception:
            print("  [手机访问] 使用 http://<电脑局域网IP>:%d" % _port)
    app.run(host=_host, port=_port, debug=_debug)
