from flask import Flask, jsonify, render_template, request, session, redirect, url_for
import requests, json, os, subprocess, glob, uuid
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if DASHBOARD_PASSWORD and not session.get("authed"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET","POST"])
def login():
    error = ""
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["authed"] = True
            return redirect("/")
        error = "Wrong password."
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Less &amp; Romance — Login</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#090909;color:#efefef;font-family:-apple-system,BlinkMacSystemFont,"Inter",sans-serif;display:flex;align-items:center;justify-content:center;height:100vh}}
.box{{width:320px;padding:40px;border:1px solid #252525;background:#111}}.ttl{{font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin-bottom:8px}}
.sub{{font-size:11px;color:#484848;margin-bottom:28px}}input{{width:100%;background:#181818;border:1px solid #252525;color:#efefef;padding:10px 14px;font-size:13px;font-family:inherit;outline:none;margin-bottom:12px}}
input:focus{{border-color:#767676}}button{{width:100%;background:#efefef;color:#090909;border:none;padding:10px;font-size:12px;font-weight:600;cursor:pointer;letter-spacing:.06em;text-transform:uppercase}}
.err{{font-size:11px;color:#b0b0b0;margin-bottom:10px}}</style></head>
<body><div class="box"><div class="ttl">Less &amp; Romance</div><div class="sub">Ops Dashboard</div>
<form method="POST">{'<div class="err">'+error+'</div>' if error else ''}
<input type="password" name="password" placeholder="Password" autofocus>
<button type="submit">Enter</button></form></div></body></html>"""

SHOPIFY_SHOP    = os.environ.get("SHOPIFY_SHOP",   "bt0wj0-5j.myshopify.com")
SHOPIFY_CID     = os.environ.get("SHOPIFY_CID",    "")
SHOPIFY_SECRET  = os.environ.get("SHOPIFY_SECRET", "")
SLACK_TOKEN     = os.environ.get("SLACK_TOKEN",    "")
CONFIG_FILE     = os.path.join(os.path.dirname(__file__), "config.json")
CHATS_FILE      = os.path.join(os.path.dirname(__file__), "chat_history.json")
REPO_ROOT       = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Commands/paths the terminal tool is allowed to run
ALLOWED_CMDS = ("ls","cat","find","grep","git","shopify","head","tail","wc","echo","pwd","env")

SLACK_CHANNELS = {
    "C09RDLEMFE2": "all-less-and-romance",
    "C09RUKS7R4Z": "üretim-planlama",
    "C0AM0V5BE8N": "operasyon",
    "C0AM77MTZQC": "managing",
    "C0AP5C353J8": "avrupa-operasyon",
    "C0APFKN8G2W": "instagram-rapor",
    "C0AVD996S4V": "ww-operation",
}

# Carrier routing — derived from real fulfilled order data
CARRIER_MAP = {
    "AE":"Aramex","SA":"Aramex","QA":"Aramex","KW":"Aramex","BH":"Aramex",
    "OM":"Aramex","JO":"Aramex","LB":"Aramex","IQ":"Aramex","EG":"Aramex",
    "PK":"Aramex","YE":"Aramex",
    "DE":"GLS","FR":"GLS","IT":"GLS","PT":"GLS","ES":"GLS","NL":"GLS",
    "BE":"GLS","PL":"GLS","CZ":"GLS","SK":"GLS","GR":"GLS","HR":"GLS",
    "LV":"GLS","LT":"GLS","EE":"GLS","LU":"GLS","MT":"GLS","RO":"GLS",
    "AT":"GLS","HU":"GLS","DK":"GLS","SE":"GLS","FI":"GLS","NO":"GLS",
    "CH":"GLS","SI":"GLS","RS":"GLS","BG":"GLS","IE":"GLS",
    "GB":"UPS","US":"UPS","CA":"UPS",
    "AU":"DHL","NZ":"DHL","SG":"DHL","JP":"DHL","KR":"DHL",
}

CARRIER_INFO = {
    "Aramex": {
        "color": "#c9a96e", "icon": "✈️",
        "regions": "Gulf & Middle East",
        "transit": "2–4 business days",
        "contact": "aramex.com",
        "track_url": "https://www.aramex.com/us/en/track/results?ShipmentNumber={n}",
        "countries": ["UAE","Saudi Arabia","Qatar","Kuwait","Bahrain","Oman","Jordan","Lebanon","Iraq","Egypt"],
    },
    "GLS": {
        "color": "#4ade80", "icon": "🚛",
        "regions": "Europe",
        "transit": "3–5 business days",
        "contact": "gls-group.com",
        "track_url": "https://gls-group.com/track/{n}",
        "countries": ["Germany","France","Italy","Portugal","Spain","Netherlands","Belgium","Poland","Greece","Croatia","Latvia","Denmark","Sweden","Finland","Norway","Austria","Czech Republic","Slovakia","Romania","Hungary"],
    },
    "UPS": {
        "color": "#a78b6e", "icon": "📦",
        "regions": "UK, USA & Canada",
        "transit": "3–6 business days",
        "contact": "ups.com",
        "track_url": "https://www.ups.com/track?tracknum={n}",
        "countries": ["United Kingdom","United States","Canada"],
    },
    "DHL": {
        "color": "#fbbf24", "icon": "🌍",
        "regions": "Asia-Pacific & Rest of World",
        "transit": "4–7 business days",
        "contact": "dhl.com",
        "track_url": "https://www.dhl.com/en/express/tracking.html?AWB={n}",
        "countries": ["Australia","New Zealand","Singapore","Japan","South Korea"],
    },
    "Other": {
        "color": "#666", "icon": "📮",
        "regions": "Various",
        "transit": "Varies",
        "contact": "17track.net",
        "track_url": "https://17track.net/en#nums={n}",
        "countries": [],
    },
}


# ── helpers ──────────────────────────────────────────────────────────────────

def shopify_token():
    r = requests.post(
        f"https://{SHOPIFY_SHOP}/admin/oauth/access_token",
        data={"grant_type":"client_credentials","client_id":SHOPIFY_CID,"client_secret":SHOPIFY_SECRET},
        timeout=10,
    )
    return r.json()["access_token"]

def shopify(path, token):
    r = requests.get(
        f"https://{SHOPIFY_SHOP}/admin/api/2024-01/{path}",
        headers={"X-Shopify-Access-Token": token}, timeout=15,
    )
    return r.json()

def estimate_carrier(cc):
    return CARRIER_MAP.get((cc or "").upper(), "Other")

def detect_carrier(company, number):
    c = (company or "").lower()
    n = (number or "").strip()
    if "aramex" in c: return "Aramex"
    if "gls" in c:    return "GLS"
    if "ups" in c:    return "UPS"
    if "dhl" in c:    return "DHL"
    if "fedex" in c:  return "FedEx"
    if n.isdigit() and len(n) == 11: return "Aramex"
    return company.title() if company and c not in ("other","") else "Other"

def tracking_link(carrier, number):
    n = number or ""
    info = CARRIER_INFO.get(carrier, CARRIER_INFO["Other"])
    return info["track_url"].format(n=n)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def anthropic_key():
    return os.environ.get("ANTHROPIC_API_KEY") or load_config().get("anthropic_api_key", "")

def load_chats():
    if os.path.exists(CHATS_FILE):
        with open(CHATS_FILE) as f:
            return json.load(f)
    return []

def write_chats(chats):
    with open(CHATS_FILE, "w") as f:
        json.dump(chats, f, indent=2)


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/chats", methods=["GET"])
@login_required
def list_chats():
    chats = load_chats()
    return jsonify({"chats": [
        {"id": c["id"], "title": c["title"], "created_at": c["created_at"],
         "message_count": len(c.get("messages", []))}
        for c in chats
    ]})

@app.route("/api/chats", methods=["POST"])
@login_required
def save_chat():
    body = request.json or {}
    messages = body.get("messages", [])
    existing_id = body.get("id")
    if not messages:
        return jsonify({"error": "empty"})
    title = next((m["content"][:60] for m in messages if m.get("role") == "user"), "Chat")
    chats = load_chats()
    if existing_id:
        for c in chats:
            if c["id"] == existing_id:
                c["messages"] = messages
                c["title"] = title
                write_chats(chats)
                return jsonify({"id": existing_id, "ok": True})
    chat = {
        "id": str(uuid.uuid4()),
        "title": title,
        "created_at": datetime.now().isoformat(),
        "messages": messages,
    }
    chats.insert(0, chat)
    write_chats(chats[:200])
    return jsonify({"id": chat["id"], "ok": True})

@app.route("/api/chats/<chat_id>", methods=["GET"])
@login_required
def get_chat(chat_id):
    chat = next((c for c in load_chats() if c["id"] == chat_id), None)
    if not chat:
        return jsonify({"error": "not found"}), 404
    return jsonify(chat)

@app.route("/api/chats/<chat_id>", methods=["DELETE"])
@login_required
def delete_chat(chat_id):
    chats = [c for c in load_chats() if c["id"] != chat_id]
    write_chats(chats)
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET","POST"])
@login_required
def config_route():
    if request.method == "POST":
        cfg = load_config()
        cfg.update(request.json or {})
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f)
        return jsonify({"ok": True})
    cfg = load_config()
    return jsonify({"has_anthropic_key": bool(anthropic_key())})


@app.route("/api/overview")
@login_required
def overview():
    token = shopify_token()
    data = shopify(
        "orders.json?status=any&limit=250"
        "&fields=id,order_number,created_at,email,fulfillment_status,"
        "total_price,shipping_address,financial_status,currency", token
    )
    orders = data.get("orders", [])
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    today_orders   = [o for o in orders if o["created_at"][:10] == today]
    yest_orders    = [o for o in orders if o["created_at"][:10] == yesterday]
    unfulfilled    = [o for o in orders if o.get("fulfillment_status") in (None,"unfulfilled","partial")]
    outside_tr     = [o for o in unfulfilled if (o.get("shipping_address") or {}).get("country_code","") != "TR"]

    today_rev  = sum(float(o.get("total_price",0)) for o in today_orders)
    yest_rev   = sum(float(o.get("total_price",0)) for o in yest_orders)
    total_rev  = sum(float(o.get("total_price",0)) for o in orders)

    country_counts = Counter()
    carrier_counts = Counter()
    for o in outside_tr:
        addr = o.get("shipping_address") or {}
        country_counts[addr.get("country","Unknown")] += 1
        carrier_counts[estimate_carrier(addr.get("country_code",""))] += 1

    email_orders = defaultdict(list)
    for o in orders:
        e = (o.get("email") or "").lower().strip()
        if e: email_orders[e].append(o["order_number"])
    returning = {e:v for e,v in email_orders.items() if len(v) >= 2}

    # Oldest unfulfilled (days waiting)
    alerts = []
    for o in sorted(outside_tr, key=lambda x: x["created_at"])[:5]:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(o["created_at"].replace("Z","+00:00"))).days
        if days >= 2:
            addr = o.get("shipping_address") or {}
            alerts.append({
                "order": o["order_number"],
                "days": days,
                "country": addr.get("country",""),
                "amount": float(o.get("total_price",0)),
            })

    recent = sorted(orders, key=lambda x: x["created_at"], reverse=True)[:20]
    recent_out = []
    for o in recent:
        addr = o.get("shipping_address") or {}
        recent_out.append({
            "number": o["order_number"],
            "date": o["created_at"][:10],
            "time": o["created_at"][11:16],
            "name": f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
            "country": addr.get("country",""),
            "country_code": addr.get("country_code",""),
            "city": addr.get("city",""),
            "amount": float(o.get("total_price",0)),
            "currency": o.get("currency","EUR"),
            "status": o.get("fulfillment_status") or "unfulfilled",
            "carrier": estimate_carrier(addr.get("country_code","")),
        })

    unfulfilled_out = []
    for o in sorted(outside_tr, key=lambda x: x["created_at"]):
        addr = o.get("shipping_address") or {}
        unfulfilled_out.append({
            "number": o["order_number"],
            "date": o["created_at"][:10],
            "name": f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
            "country": addr.get("country",""),
            "country_code": addr.get("country_code",""),
            "city": addr.get("city",""),
            "amount": float(o.get("total_price",0)),
            "currency": o.get("currency","EUR"),
            "carrier": estimate_carrier(addr.get("country_code","")),
        })

    return jsonify({
        "today_orders":        len(today_orders),
        "yest_orders":         len(yest_orders),
        "today_revenue":       round(today_rev, 2),
        "yest_revenue":        round(yest_rev, 2),
        "total_orders":        len(orders),
        "total_revenue":       round(total_rev, 2),
        "unfulfilled_outside_tr": len(outside_tr),
        "returning_customers": len(returning),
        "top_countries":       country_counts.most_common(8),
        "by_carrier":          carrier_counts.most_common(),
        "alerts":              alerts,
        "recent_orders":       recent_out,
        "unfulfilled_orders":  unfulfilled_out,
        "last_updated":        datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/fulfilled")
@login_required
def fulfilled():
    token = shopify_token()
    data = shopify(
        "orders.json?fulfillment_status=fulfilled&status=any&limit=250"
        "&fields=order_number,created_at,shipping_address,total_price,currency,fulfillments",
        token,
    )
    orders = data.get("orders", [])
    intl = [o for o in orders if (o.get("shipping_address") or {}).get("country_code","") != "TR"]

    by_carrier = defaultdict(list)
    for o in sorted(intl, key=lambda x: x["created_at"], reverse=True):
        addr = o.get("shipping_address") or {}
        for f in o.get("fulfillments", []):
            company = f.get("tracking_company") or ""
            number  = f.get("tracking_number") or ""
            carrier = detect_carrier(company, number)
            link    = f.get("tracking_url") or tracking_link(carrier, number)
            by_carrier[carrier].append({
                "number":   o["order_number"],
                "date":     (f.get("created_at") or o["created_at"])[:10],
                "name":     f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
                "country":  addr.get("country",""),
                "city":     addr.get("city",""),
                "amount":   float(o.get("total_price",0)),
                "currency": o.get("currency","EUR"),
                "tracking_number": number,
                "tracking_link":   link,
            })

    carriers_out = [
        {"carrier": k, "count": len(v), "orders": v}
        for k, v in sorted(by_carrier.items())
    ]
    return jsonify({"carriers": carriers_out, "total": len(intl)})


@app.route("/api/carriers")
@login_required
def carriers():
    token = shopify_token()
    # Unfulfilled (for queue per carrier)
    data = shopify(
        "orders.json?status=open&fulfillment_status=unfulfilled&limit=250"
        "&fields=order_number,created_at,shipping_address,total_price,currency",
        token,
    )
    unfulfilled = data.get("orders", [])
    outside_tr  = [o for o in unfulfilled if (o.get("shipping_address") or {}).get("country_code","") != "TR"]

    # Fulfilled (in-transit)
    fdata = shopify(
        "orders.json?fulfillment_status=fulfilled&status=any&limit=250"
        "&fields=order_number,created_at,shipping_address,total_price,currency,fulfillments",
        token,
    )
    fulfilled_orders = [
        o for o in fdata.get("orders",[])
        if (o.get("shipping_address") or {}).get("country_code","") != "TR"
    ]

    carrier_queue   = defaultdict(list)
    carrier_transit = defaultdict(list)

    for o in outside_tr:
        addr    = o.get("shipping_address") or {}
        carrier = estimate_carrier(addr.get("country_code",""))
        carrier_queue[carrier].append({
            "number":  o["order_number"],
            "date":    o["created_at"][:10],
            "name":    f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
            "country": addr.get("country",""),
            "city":    addr.get("city",""),
            "amount":  float(o.get("total_price",0)),
            "currency":o.get("currency","EUR"),
        })

    for o in fulfilled_orders:
        addr = o.get("shipping_address") or {}
        for f in o.get("fulfillments",[]):
            company = f.get("tracking_company") or ""
            number  = f.get("tracking_number") or ""
            carrier = detect_carrier(company, number)
            if carrier == "Other":
                carrier = estimate_carrier(addr.get("country_code",""))
            shipped_date = (f.get("created_at") or o["created_at"])[:10]
            # estimate transit days
            info  = CARRIER_INFO.get(carrier, CARRIER_INFO["Other"])
            days_ago = (datetime.now(timezone.utc).date() -
                        datetime.strptime(shipped_date, "%Y-%m-%d").date()).days
            carrier_transit[carrier].append({
                "number":          o["order_number"],
                "shipped_date":    shipped_date,
                "days_in_transit": days_ago,
                "name":            f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
                "country":         addr.get("country",""),
                "city":            addr.get("city",""),
                "amount":          float(o.get("total_price",0)),
                "currency":        o.get("currency","EUR"),
                "tracking_number": f.get("tracking_number",""),
                "tracking_link":   f.get("tracking_url") or tracking_link(carrier, f.get("tracking_number","")),
            })

    result = []
    for carrier, info in CARRIER_INFO.items():
        queue   = carrier_queue.get(carrier, [])
        transit = carrier_transit.get(carrier, [])
        if not queue and not transit:
            continue
        result.append({
            "carrier":  carrier,
            "info":     info,
            "queue":    sorted(queue, key=lambda x: x["date"]),
            "transit":  sorted(transit, key=lambda x: x["days_in_transit"], reverse=True)[:20],
            "queue_count":   len(queue),
            "transit_count": len(transit),
        })

    return jsonify({"carriers": result})


@app.route("/api/slack")
@login_required
def slack():
    all_messages = []
    for ch_id, ch_name in SLACK_CHANNELS.items():
        r = requests.get(
            "https://slack.com/api/conversations.history",
            params={"channel": ch_id, "limit": 6},
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            timeout=8,
        ).json()
        if r.get("ok"):
            for m in r.get("messages", []):
                text = (m.get("text") or "").strip()
                if not text or text.startswith("<"): continue
                ts = float(m.get("ts", 0))
                all_messages.append({
                    "channel": ch_name,
                    "text":    text[:300],
                    "ts":      ts,
                    "time":    datetime.fromtimestamp(ts).strftime("%d %b %H:%M"),
                })

    all_messages.sort(key=lambda x: x["ts"], reverse=True)
    return jsonify({"messages": all_messages[:30]})


@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    key = anthropic_key()
    if not key:
        return jsonify({"error": "no_key", "message": "Anthropic API key not configured."})

    try:
        import anthropic as ac
    except ImportError:
        return jsonify({"error": "no_sdk", "message": "Anthropic SDK not installed."})

    body     = request.json or {}
    messages = body.get("messages", [])

    client = ac.Anthropic(api_key=key)

    tools = [
        {
            "name": "read_repo_file",
            "description": "Read a file from the fabricfleet repository. Use to answer questions about config, context docs, ops notes, credentials setup, etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from repo root, e.g. context/oplog-shopify.md or README.md"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_repo_files",
            "description": "List files and folders in the fabricfleet repository or a subdirectory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from repo root. Use '.' for root."},
                },
            },
        },
        {
            "name": "search_repo",
            "description": "Search for a keyword or phrase across all files in the fabricfleet repo.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "run_terminal",
            "description": "Run a safe read-only terminal command (ls, git, grep, shopify store execute, etc.). Do NOT run destructive commands.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
        {
            "name": "get_orders",
            "description": "Fetch orders from the Shopify store. Use to answer questions about orders, revenue, customers.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "status":              {"type":"string","description":"all, open, closed, cancelled"},
                    "fulfillment_status":  {"type":"string","description":"unfulfilled, fulfilled, partial, any"},
                    "limit":               {"type":"integer","description":"max 250"},
                    "created_at_min":      {"type":"string","description":"ISO date like 2026-04-28"},
                },
            },
        },
        {
            "name": "get_order_detail",
            "description": "Get full details of a specific order including fulfillment and tracking.",
            "input_schema": {
                "type": "object",
                "properties": {"order_number": {"type":"integer"}},
                "required": ["order_number"],
            },
        },
        {
            "name": "search_customer",
            "description": "Find all orders by a customer email or name.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type":"string","description":"email or name to search"},
                },
                "required": ["query"],
            },
        },
    ]

    system = f"""You are the operations AI assistant for Less & Romance, a fashion brand based in Istanbul.
Today is {datetime.now().strftime('%A, %B %d %Y')}, Istanbul time.
Store: {SHOPIFY_SHOP}
Carriers: Aramex (Gulf/Middle East), GLS (Europe), UPS (UK/US/Canada), DHL (Asia-Pacific).
Warehouse: Tuzla OSB, Istanbul (Oplog). Contact: Mesut Bey +90 543 145 48 60.
Repo: fabricfleet at {REPO_ROOT} — contains context docs, ops notes, credentials setup, API configs.
Key context files: context/oplog-shopify.md, context/slack.md, context/shopify-cli.md, context/lessandromance-ops.md.

You have access to:
- Shopify live order data (get_orders, get_order_detail, search_customer)
- The fabricfleet repo files (read_repo_file, list_repo_files, search_repo)
- Terminal commands for read-only ops (run_terminal) — git, shopify CLI, grep, ls, etc.

Keep answers concise. Use tools to look up live data. Format numbers nicely. Use € for EUR amounts."""

    def run_tool(name, inp, token):
        if name == "read_repo_file":
            rel = inp.get("path","").lstrip("/")
            full = os.path.normpath(os.path.join(REPO_ROOT, rel))
            if not full.startswith(REPO_ROOT):
                return {"error": "Path outside repo"}
            if not os.path.exists(full):
                return {"error": f"File not found: {rel}"}
            with open(full, "r", errors="replace") as f:
                content = f.read(20000)
            return {"path": rel, "content": content}

        elif name == "list_repo_files":
            rel  = (inp.get("path") or ".").lstrip("/")
            full = os.path.normpath(os.path.join(REPO_ROOT, rel))
            if not full.startswith(REPO_ROOT):
                return {"error": "Path outside repo"}
            if not os.path.exists(full):
                return {"error": f"Path not found: {rel}"}
            entries = []
            for item in sorted(os.listdir(full)):
                item_path = os.path.join(full, item)
                entries.append({"name": item, "type": "dir" if os.path.isdir(item_path) else "file"})
            return {"path": rel, "entries": entries}

        elif name == "search_repo":
            query = inp.get("query","")
            try:
                result = subprocess.run(
                    ["grep", "-r", "--include=*.md", "--include=*.json", "--include=*.js",
                     "--include=*.py", "--include=*.toml", "-l", "-i", query, REPO_ROOT],
                    capture_output=True, text=True, timeout=10
                )
                files = [f.replace(REPO_ROOT+"/","") for f in result.stdout.strip().split("\n") if f]
                # get matching lines from first 5 files
                matches = []
                for f in files[:5]:
                    full = os.path.join(REPO_ROOT, f)
                    res2 = subprocess.run(["grep", "-n", "-i", query, full],
                                          capture_output=True, text=True, timeout=5)
                    for line in res2.stdout.strip().split("\n")[:5]:
                        if line: matches.append({"file": f, "line": line})
                return {"files_found": len(files), "files": files, "sample_matches": matches}
            except Exception as e:
                return {"error": str(e)}

        elif name == "run_terminal":
            command = inp.get("command","").strip()
            first_word = command.split()[0] if command else ""
            if first_word not in ALLOWED_CMDS:
                return {"error": f"Command '{first_word}' not allowed. Allowed: {', '.join(ALLOWED_CMDS)}"}
            try:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=20, cwd=REPO_ROOT
                )
                return {
                    "stdout": result.stdout[:5000],
                    "stderr": result.stderr[:1000] if result.stderr else "",
                    "exit_code": result.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"error": "Command timed out"}
            except Exception as e:
                return {"error": str(e)}

        elif name == "get_orders":
            params = "status=any&limit=250&fields=order_number,created_at,email,fulfillment_status,total_price,shipping_address,currency"
            if inp.get("fulfillment_status") and inp["fulfillment_status"] != "any":
                params += f"&fulfillment_status={inp['fulfillment_status']}"
            if inp.get("created_at_min"):
                params += f"&created_at_min={inp['created_at_min']}T00:00:00Z"
            data = shopify(f"orders.json?{params}", token)
            orders = data.get("orders", [])
            if inp.get("status") and inp["status"] != "all":
                orders = [o for o in orders if o.get("financial_status") == inp["status"] or True]
            result = []
            for o in orders[:50]:
                addr = o.get("shipping_address") or {}
                result.append({
                    "order": o["order_number"],
                    "date":  o["created_at"][:10],
                    "email": o.get("email",""),
                    "name":  f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
                    "country": addr.get("country",""),
                    "amount": float(o.get("total_price",0)),
                    "currency": o.get("currency","EUR"),
                    "status": o.get("fulfillment_status") or "unfulfilled",
                })
            total_rev = sum(r["amount"] for r in result)
            return {"count": len(result), "total_revenue_eur": round(total_rev,2), "orders": result}

        elif name == "get_order_detail":
            num = inp["order_number"]
            data = shopify(f"orders.json?name=%23{num}&status=any&limit=1", token)
            orders = data.get("orders",[])
            if not orders:
                return {"error": f"Order #{num} not found"}
            o = orders[0]
            addr = o.get("shipping_address") or {}
            fuls = []
            for f in o.get("fulfillments",[]):
                company = f.get("tracking_company","")
                number  = f.get("tracking_number","")
                carrier = detect_carrier(company, number)
                fuls.append({
                    "status": f.get("status"),
                    "carrier": carrier,
                    "tracking_number": number,
                    "tracking_link": f.get("tracking_url") or tracking_link(carrier, number),
                    "shipped_at": (f.get("created_at") or "")[:10],
                })
            line_items = []
            for item in o.get("line_items", []):
                line_items.append({
                    "product": item.get("title", ""),
                    "variant": item.get("variant_title", ""),
                    "sku": item.get("sku", ""),
                    "quantity": item.get("quantity", 1),
                    "price": float(item.get("price", 0)),
                    "total": float(item.get("price", 0)) * item.get("quantity", 1),
                })
            return {
                "order": o["order_number"],
                "date": o["created_at"][:10],
                "name": f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
                "email": o.get("email",""),
                "phone": addr.get("phone",""),
                "address": f"{addr.get('address1','')} {addr.get('city','')} {addr.get('country','')}".strip(),
                "amount": float(o.get("total_price",0)),
                "currency": o.get("currency","EUR"),
                "fulfillment_status": o.get("fulfillment_status") or "unfulfilled",
                "line_items": line_items,
                "fulfillments": fuls,
            }

        elif name == "search_customer":
            q = (inp.get("query") or "").lower()
            data = shopify(
                f"orders.json?status=any&limit=250&fields=order_number,created_at,email,total_price,currency,shipping_address,fulfillment_status",
                token
            )
            orders = data.get("orders",[])
            matched = []
            for o in orders:
                addr = o.get("shipping_address") or {}
                name = f"{addr.get('first_name','')} {addr.get('last_name','')}".lower()
                email = (o.get("email") or "").lower()
                if q in name or q in email:
                    matched.append({
                        "order":   o["order_number"],
                        "date":    o["created_at"][:10],
                        "email":   o.get("email",""),
                        "name":    f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
                        "country": addr.get("country",""),
                        "amount":  float(o.get("total_price",0)),
                        "status":  o.get("fulfillment_status") or "unfulfilled",
                    })
            return {"count": len(matched), "orders": matched}

        return {"error": "unknown tool"}

    token = shopify_token()
    claude_msgs = list(messages)
    max_loops = 5

    for _ in range(max_loops):
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system,
            tools=tools,
            messages=claude_msgs,
        )

        if resp.stop_reason == "end_turn":
            text = next((b.text for b in resp.content if hasattr(b,"text")), "")
            return jsonify({"reply": text})

        if resp.stop_reason == "tool_use":
            claude_msgs.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input, token)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(result),
                    })
            claude_msgs.append({"role": "user", "content": tool_results})
        else:
            break

    return jsonify({"reply": "Something went wrong. Try again."})


STAGE_THRESHOLDS = {
    "Aramex": {"in_transit": 1, "out_for_delivery": 3},
    "GLS":    {"in_transit": 1, "out_for_delivery": 4},
    "UPS":    {"in_transit": 1, "out_for_delivery": 5},
    "DHL":    {"in_transit": 1, "out_for_delivery": 6},
    "Other":  {"in_transit": 1, "out_for_delivery": 5},
}
CARRIER_MAX_DAYS = {"Aramex": 5, "GLS": 6, "UPS": 7, "DHL": 8, "Other": 7}

# Shopify shipment_status → stage (source of truth when available)
SHOPIFY_STATUS_STAGE = {
    "confirmed":          1,
    "in_transit":         2,
    "out_for_delivery":   3,
    "attempted_delivery": 3,
    "ready_for_pickup":   3,
    "delivered":          4,
    "failure":            3,
}

def estimate_stage(carrier, days, shipment_status=None):
    # Use Shopify's live carrier status if present — never override with time estimate
    if shipment_status and shipment_status in SHOPIFY_STATUS_STAGE:
        return SHOPIFY_STATUS_STAGE[shipment_status]
    # Time-based fallback: cap at stage 3 — NEVER auto-mark delivered
    t = STAGE_THRESHOLDS.get(carrier, STAGE_THRESHOLDS["Other"])
    if days >= t["out_for_delivery"]: return 3
    if days >= t["in_transit"]:       return 2
    return 1

def estimate_delivery(carrier, shipped_str):
    max_days = CARRIER_MAX_DAYS.get(carrier, 7)
    shipped = datetime.strptime(shipped_str, "%Y-%m-%d").date()
    return (shipped + timedelta(days=max_days)).isoformat()


@app.route("/api/tracking")
@login_required
def tracking_tab():
    token = shopify_token()

    # ── Unfulfilled international orders (stage 0 — awaiting Oplog action) ──
    unf_data = shopify(
        "orders.json?status=open&fulfillment_status=unfulfilled&limit=250"
        "&fields=order_number,created_at,shipping_address,total_price,currency",
        token,
    )
    unf_intl = [
        o for o in unf_data.get("orders", [])
        if (o.get("shipping_address") or {}).get("country_code","") != "TR"
    ]

    # ── Fulfilled international orders (stages 1–4) ──
    ful_data = shopify(
        "orders.json?fulfillment_status=fulfilled&status=any&limit=250"
        "&fields=order_number,created_at,shipping_address,total_price,currency,fulfillments",
        token,
    )
    ful_intl = [
        o for o in ful_data.get("orders", [])
        if (o.get("shipping_address") or {}).get("country_code","") != "TR"
    ]

    today = datetime.now(timezone.utc).date()
    result = []

    # Stage 0 — unfulfilled
    for o in unf_intl:
        addr    = o.get("shipping_address") or {}
        cc      = addr.get("country_code", "")
        carrier = estimate_carrier(cc)
        order_date  = o["created_at"][:10]
        days_waiting = (today - datetime.strptime(order_date, "%Y-%m-%d").date()).days
        result.append({
            "number":          o["order_number"],
            "name":            f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
            "country":         addr.get("country",""),
            "country_code":    cc,
            "city":            addr.get("city",""),
            "carrier":         carrier,
            "order_date":      order_date,
            "shipped_date":    "",
            "days_in_transit": 0,
            "days_waiting":    days_waiting,
            "stage":           0,
            "shipment_status": "unfulfilled",
            "status_source":   "pending",
            "tracking_number": "",
            "tracking_link":   "",
            "est_delivery":    "",
            "amount":          float(o.get("total_price", 0)),
            "currency":        o.get("currency","EUR"),
        })

    # Stages 1–4 — fulfilled
    for o in ful_intl:
        addr = o.get("shipping_address") or {}
        cc   = addr.get("country_code", "")
        for f in o.get("fulfillments", []):
            company         = f.get("tracking_company") or ""
            number          = f.get("tracking_number") or ""
            shipment_status = f.get("shipment_status")
            carrier = detect_carrier(company, number)
            if carrier == "Other":
                carrier = estimate_carrier(cc)
            shipped_date = (f.get("created_at") or o["created_at"])[:10]
            days  = (today - datetime.strptime(shipped_date, "%Y-%m-%d").date()).days
            stage = estimate_stage(carrier, days, shipment_status)
            status_source = "live" if (shipment_status and shipment_status in SHOPIFY_STATUS_STAGE) else "estimated"
            result.append({
                "number":          o["order_number"],
                "name":            f"{addr.get('first_name','')} {addr.get('last_name','')}".strip(),
                "country":         addr.get("country",""),
                "country_code":    cc,
                "city":            addr.get("city",""),
                "carrier":         carrier,
                "order_date":      o["created_at"][:10],
                "shipped_date":    shipped_date,
                "days_in_transit": days,
                "days_waiting":    0,
                "stage":           stage,
                "shipment_status": shipment_status or "unknown",
                "status_source":   status_source,
                "tracking_number": number,
                "tracking_link":   f.get("tracking_url") or tracking_link(carrier, number),
                "est_delivery":    estimate_delivery(carrier, shipped_date),
                "amount":          float(o.get("total_price", 0)),
                "currency":        o.get("currency","EUR"),
            })

    # Sort: unfulfilled oldest first, then by days_in_transit desc
    result.sort(key=lambda x: (-x["days_waiting"] if x["stage"] == 0 else 0, -x["days_in_transit"]))
    return jsonify({"shipments": result, "total": len(result), "unfulfilled_count": len(unf_intl)})


@app.route("/api/analytics")
@login_required
def analytics():
    token = shopify_token()
    ist = timezone(timedelta(hours=3))
    today = datetime.now(ist).date().isoformat()

    data = shopify(
        f"orders.json?status=any&created_at_min={today}T00:00:00%2B03:00&limit=250"
        "&fields=id,order_number,line_items,shipping_address",
        token,
    )
    orders = data.get("orders", [])

    COLORS = ["BUTTER YELLOW","BABY BLUE","GREY MELANGE","BURGUNDY","STONE","BLACK","WHITE","BITTER COFFEE","MINK"]

    color_counts   = Counter()
    country_counts = Counter()
    color_by_country  = defaultdict(lambda: defaultdict(int))
    country_by_color  = defaultdict(lambda: defaultdict(int))

    for o in orders:
        addr    = o.get("shipping_address") or {}
        country = addr.get("country", "Unknown")
        country_counts[country] += 1
        for item in o.get("line_items", []):
            title = item.get("title", "").upper()
            qty   = item.get("quantity", 1)
            for color in COLORS:
                if color in title:
                    color_counts[color] += qty
                    color_by_country[color][country] += qty
                    country_by_color[country][color] += qty

    return jsonify({
        "date":           today,
        "total_orders":   len(orders),
        "colors":         color_counts.most_common(),
        "countries":      country_counts.most_common(),
        "color_by_country": {
            col: sorted(v.items(), key=lambda x: -x[1])
            for col, v in color_by_country.items()
        },
        "country_by_color": {
            cn: sorted(v.items(), key=lambda x: -x[1])
            for cn, v in country_by_color.items()
        },
    })


@app.route("/")
@login_required
def index():
    return render_template("index.html")


if __name__ == "__main__":
    import webbrowser, threading, time
    def open_browser():
        time.sleep(1)
        webbrowser.open("http://localhost:5050")
    threading.Thread(target=open_browser, daemon=True).start()
    print("Less & Romance Dashboard → http://localhost:5050")
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
