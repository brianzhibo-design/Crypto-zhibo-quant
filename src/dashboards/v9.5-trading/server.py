#!/usr/bin/env python3
import os, time, json
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import redis
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = Flask(__name__, static_folder='.')
CORS(app, resources={r"/*": {"origins": "*"}})

# 从环境变量读取 Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

def now_ms():
    return int(time.time() * 1000)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,DELETE,OPTIONS')
    return response

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/api/stats")
def api_stats():
    try:
        hb = redis_client.hgetall("node:heartbeat:FUSION")
        return jsonify({"processed": int(hb.get("processed", 0)), "fused": int(hb.get("fused", 0))})
    except:
        return jsonify({"processed": 0, "fused": 0})

@app.route("/api/events/latest")
def api_events_latest():
    events = []
    try:
        for event_id, data in redis_client.xrevrange("events:fused", count=50):
            events.append({"id": event_id, "symbols": data.get("symbols", "UNKNOWN"), "source": data.get("source", "unknown"), "exchange": data.get("exchange", ""), "score": float(data.get("score", 0)), "ts": data.get("ts", str(now_ms())), "raw_text": data.get("raw_text", ""), "source_count": data.get("source_count", "1")})
    except Exception as e:
        print(f"Error: {e}")
    return jsonify(events)

@app.route("/api/events/super")
def api_events_super():
    events = []
    try:
        for event_id, data in redis_client.xrevrange("events:fused", count=200):
            sc = int(data.get("source_count", "1"))
            if sc >= 2 or float(data.get("score", 0)) > 50:
                events.append({"id": event_id, "symbols": data.get("symbols", "UNKNOWN"), "source": data.get("source", "unknown"), "exchange": data.get("exchange", ""), "score": float(data.get("score", 0)), "ts": data.get("ts", str(now_ms())), "source_count": sc, "raw_text": data.get("raw_text", "")})
                if len(events) >= 20: break
    except:
        pass
    return jsonify(events)

@app.route("/api/status")
def api_status():
    status = {"nodes": {}}
    try:
        for key in redis_client.scan_iter("node:heartbeat:*"):
            node_name = key.split("node:heartbeat:")[-1]
            hb = redis_client.hgetall(key)
            ttl = redis_client.ttl(key)
            status["nodes"][node_name] = {"status": "online" if ttl > 0 else "offline", "processed": int(hb.get("processed", 0)), "ttl": ttl}
    except:
        pass
    return jsonify(status)

@app.route("/api/analytics/exchange-ranking")
def api_exchange_ranking():
    counts = {}
    try:
        for key in redis_client.scan_iter("coin:seen:*"):
            parts = key.split(":")
            if len(parts) >= 3: counts[parts[2]] = counts.get(parts[2], 0) + 1
    except:
        pass
    total = sum(counts.values()) or 1
    return jsonify([{"name": k, "count": v, "super_rate": round(v/total*100, 1)} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]])

@app.route("/api/analytics/ai-insight")
def api_ai_insight():
    try:
        items = redis_client.xrevrange("events:fused", count=30)
        if not items:
            return jsonify({"summary": "暂无融合事件数据...", "generated_at": now_ms()})
        
        symbols, exchanges = set(), set()
        for _, data in items:
            if data.get("symbols"): symbols.add(data["symbols"])
            if data.get("exchange"): exchanges.add(data["exchange"])
        
        summary = f"检测到 {len(items)} 个融合事件，涉及 {len(exchanges)} 个交易所，{len(symbols)} 个交易对。"
        
        if OPENAI_API_KEY:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=OPENAI_API_KEY)
                texts = [f"{d.get('symbols','')} @ {d.get('exchange','')}" for _,d in items[:20]]
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是加密货币市场监控助手，用简短中文总结，不超过50字。"},
                        {"role": "user", "content": f"总结事件：\n" + "\n".join(texts)}
                    ],
                    max_tokens=100,
                    temperature=0.3,
                )
                summary = response.choices[0].message.content
            except Exception as e:
                summary = f"AI暂不可用: {str(e)[:60]}"
        
        return jsonify({"summary": summary, "generated_at": now_ms()})
    except Exception as e:
        return jsonify({"summary": f"错误: {str(e)[:50]}", "generated_at": now_ms()})

@app.route("/api/analytics/alpha-ranking")
def api_alpha_ranking():
    rankings, seen = [], set()
    try:
        for event_id, data in redis_client.xrevrange("events:fused", count=100):
            sym = data.get("symbols", "")
            if sym and sym not in seen:
                seen.add(sym)
                ts = int(data.get("ts", now_ms()))
                ago = (now_ms() - ts) // 1000
                time_ago = f"{ago}s ago" if ago < 60 else f"{ago//60}m ago" if ago < 3600 else f"{ago//3600}h ago"
                rankings.append({"id": event_id, "symbols": sym, "exchange": data.get("exchange", ""), "score": float(data.get("score", 0)), "time_ago": time_ago, "ts": data.get("ts", ""), "raw_text": data.get("raw_text", "")})
                if len(rankings) >= 10: break
    except:
        pass
    rankings.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"rankings": rankings})

@app.route("/api/analytics/exchange-leadlag")
def api_exchange_leadlag():
    return jsonify({"rankings": []})

@app.route("/api/alerts/rules", methods=["GET", "POST", "OPTIONS"])
def api_alert_rules():
    if request.method == "OPTIONS": return jsonify({"ok": True})
    if request.method == "GET": return jsonify([])
    rule = request.json or {}
    rule.setdefault("id", f"rule-{now_ms()}")
    return jsonify(rule), 201

@app.route("/api/alerts/rules/<rid>", methods=["DELETE", "OPTIONS"])
def api_alert_delete(rid):
    return jsonify({"deleted": True})

@app.route("/api/alerts/test", methods=["POST", "OPTIONS"])
def api_alert_test():
    return jsonify({"matches": []})

@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").upper()
    if len(q) < 2: return jsonify({"results": []})
    results = []
    try:
        for event_id, data in redis_client.xrevrange("events:fused", count=200):
            if q in f"{data.get('symbols','')} {data.get('exchange','')}".upper():
                results.append({"id": event_id, "symbols": data.get("symbols",""), "exchange": data.get("exchange",""), "score": float(data.get("score",0))})
                if len(results) >= 20: break
    except:
        pass
    return jsonify({"results": results})

if __name__ == "__main__":
    print(f"🚀 Fusion Dashboard v9.5 @ http://0.0.0.0:5001")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
