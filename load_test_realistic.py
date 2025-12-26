import requests
import time
import concurrent.futures
import statistics
import random
import json

BASE_URL = "https://web-production-d70f.up.railway.app"

results = []

def api_request(method, endpoint, data=None, name=""):
    start = time.time()
    try:
        url = f"{BASE_URL}{endpoint}"
        if method == "GET":
            resp = requests.get(url, timeout=15)
        elif method == "POST":
            resp = requests.post(url, json=data, timeout=15)
        elif method == "PUT":
            resp = requests.put(url, json=data, timeout=15)
        elapsed = (time.time() - start) * 1000
        return {
            "name": name,
            "method": method,
            "endpoint": endpoint,
            "status": resp.status_code,
            "time_ms": elapsed,
            "success": resp.status_code < 400
        }
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {
            "name": name,
            "method": method,
            "endpoint": endpoint,
            "status": 0,
            "time_ms": elapsed,
            "success": False,
            "error": str(e)
        }

print("=" * 65)
print("🎭 リアル店舗シミュレーションテスト")
print("=" * 65)
print("""
シナリオ: 金曜深夜のピーク時間
- 20卓中15卓が稼働中
- スタッフ10人が管理画面を操作
- 各テーブルから注文が飛び交う
- 3テーブルが同時に精算処理
""")

# ========== 1. 初期データ取得（全員がページロード）==========
print("\n" + "=" * 65)
print("📱 フェーズ1: 全員がページを開く（30人同時）")
print("=" * 65)

def initial_load(user_id):
    """ページ初期ロード: 複数API同時取得"""
    res = []
    res.append(api_request("GET", "/api/tables", name=f"User{user_id}"))
    res.append(api_request("GET", "/api/menu", name=f"User{user_id}"))
    res.append(api_request("GET", "/api/sessions/active", name=f"User{user_id}"))
    res.append(api_request("GET", "/api/casts", name=f"User{user_id}"))
    res.append(api_request("GET", "/api/orders", name=f"User{user_id}"))
    return res

phase1_results = []
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
    futures = [ex.submit(initial_load, i) for i in range(30)]
    for f in concurrent.futures.as_completed(futures):
        phase1_results.extend(f.result())
phase1_time = time.time() - start

ok = [r for r in phase1_results if r["success"]]
times = [r["time_ms"] for r in ok]
print(f"   リクエスト数: {len(phase1_results)}")
print(f"   成功率: {len(ok)/len(phase1_results)*100:.1f}%")
print(f"   実行時間: {phase1_time:.2f}秒")
print(f"   平均: {statistics.mean(times):.0f}ms / 最大: {max(times):.0f}ms")

# ========== 2. 注文ラッシュ（POST多数）==========
print("\n" + "=" * 65)
print("🍺 フェーズ2: 注文ラッシュ（10テーブルから同時注文）")
print("=" * 65)

def order_rush(table_num):
    """テーブルからの注文（POST）"""
    res = []
    # メニューID 160-163 あたりをランダムに
    for _ in range(random.randint(1, 3)):
        order_data = {
            "session_id": 13,  # 実際のセッションID
            "menu_item_id": random.choice([160, 161, 162, 163]),
            "quantity": random.randint(1, 2),
            "is_drink_back": random.choice([True, False]),
            "item_name": f"テスト注文{table_num}"
        }
        res.append(api_request("POST", "/api/orders", order_data, f"Table{table_num}"))
        time.sleep(0.1)  # 連続注文の間隔
    return res

phase2_results = []
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    futures = [ex.submit(order_rush, i) for i in range(10)]
    for f in concurrent.futures.as_completed(futures):
        phase2_results.extend(f.result())
phase2_time = time.time() - start

ok = [r for r in phase2_results if r["success"]]
times = [r["time_ms"] for r in ok]
print(f"   注文数: {len(phase2_results)}")
print(f"   成功率: {len(ok)/len(phase2_results)*100:.1f}%")
print(f"   実行時間: {phase2_time:.2f}秒")
if times:
    print(f"   平均: {statistics.mean(times):.0f}ms / 最大: {max(times):.0f}ms")

# ========== 3. スタッフ操作（オーダー確認の連打）==========
print("\n" + "=" * 65)
print("👨‍💼 フェーズ3: スタッフがオーダー確認を連打")
print("=" * 65)

def staff_check_orders(staff_id):
    """スタッフ: オーダー管理の更新連打"""
    res = []
    for _ in range(5):
        res.append(api_request("GET", "/api/orders", name=f"Staff{staff_id}"))
        time.sleep(0.2)
    return res

phase3_results = []
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    futures = [ex.submit(staff_check_orders, i) for i in range(10)]
    for f in concurrent.futures.as_completed(futures):
        phase3_results.extend(f.result())
phase3_time = time.time() - start

ok = [r for r in phase3_results if r["success"]]
times = [r["time_ms"] for r in ok]
print(f"   リクエスト数: {len(phase3_results)}")
print(f"   成功率: {len(ok)/len(phase3_results)*100:.1f}%")
print(f"   実行時間: {phase3_time:.2f}秒")
if times:
    print(f"   平均: {statistics.mean(times):.0f}ms / 最大: {max(times):.0f}ms")

# ========== 4. 混合負荷（GET + POST 同時）==========
print("\n" + "=" * 65)
print("🔥 フェーズ4: カオス状態（注文+確認+更新が同時発生）")
print("=" * 65)

def chaos_action(user_id):
    """ランダムな操作"""
    res = []
    action = random.choice(["order", "check", "tables", "menu"])
    
    if action == "order":
        order_data = {
            "session_id": 13,
            "menu_item_id": random.choice([160, 161, 162, 163]),
            "quantity": 1,
            "is_drink_back": False
        }
        res.append(api_request("POST", "/api/orders", order_data, f"Chaos{user_id}"))
    elif action == "check":
        res.append(api_request("GET", "/api/orders", name=f"Chaos{user_id}"))
    elif action == "tables":
        res.append(api_request("GET", "/api/tables", name=f"Chaos{user_id}"))
        res.append(api_request("GET", "/api/sessions/active", name=f"Chaos{user_id}"))
    else:
        res.append(api_request("GET", "/api/menu", name=f"Chaos{user_id}"))
    
    return res

phase4_results = []
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=40) as ex:
    futures = [ex.submit(chaos_action, i) for i in range(100)]
    for f in concurrent.futures.as_completed(futures):
        phase4_results.extend(f.result())
phase4_time = time.time() - start

ok = [r for r in phase4_results if r["success"]]
fail = [r for r in phase4_results if not r["success"]]
times = [r["time_ms"] for r in ok]
print(f"   リクエスト数: {len(phase4_results)}")
print(f"   成功率: {len(ok)/len(phase4_results)*100:.1f}%")
print(f"   失敗数: {len(fail)}")
print(f"   実行時間: {phase4_time:.2f}秒")
if times:
    print(f"   平均: {statistics.mean(times):.0f}ms / 最大: {max(times):.0f}ms")
    sorted_times = sorted(times)
    p95 = sorted_times[int(len(sorted_times)*0.95)]
    print(f"   95%タイル: {p95:.0f}ms")

if fail:
    print(f"\n   ❌ 失敗例:")
    for f in fail[:3]:
        print(f"      {f['method']} {f['endpoint']}: {f.get('error', f['status'])}")

# ========== 5. 長時間稼働シミュレーション ==========
print("\n" + "=" * 65)
print("⏰ フェーズ5: 長時間稼働（15秒間の連続リクエスト）")
print("=" * 65)

phase5_results = []
start = time.time()
request_count = 0
while time.time() - start < 15:
    res = api_request("GET", "/api/orders", name="LongRun")
    phase5_results.append(res)
    request_count += 1
    time.sleep(0.1)  # 100msごと

ok = [r for r in phase5_results if r["success"]]
times = [r["time_ms"] for r in ok]
print(f"   リクエスト数: {len(phase5_results)}")
print(f"   成功率: {len(ok)/len(phase5_results)*100:.1f}%")
print(f"   スループット: {request_count/15:.1f} req/sec")
if times:
    print(f"   平均: {statistics.mean(times):.0f}ms")
    # 時系列での性能劣化チェック
    first_10 = times[:10]
    last_10 = times[-10:]
    print(f"   最初10件平均: {statistics.mean(first_10):.0f}ms")
    print(f"   最後10件平均: {statistics.mean(last_10):.0f}ms")
    degradation = (statistics.mean(last_10) - statistics.mean(first_10)) / statistics.mean(first_10) * 100
    print(f"   性能劣化: {degradation:+.1f}%")

# ========== 総合評価 ==========
print("\n" + "=" * 65)
print("📊 総合評価")
print("=" * 65)

all_results = phase1_results + phase2_results + phase3_results + phase4_results + phase5_results
all_ok = [r for r in all_results if r["success"]]
all_times = [r["time_ms"] for r in all_ok]

total_success_rate = len(all_ok) / len(all_results) * 100
avg_time = statistics.mean(all_times) if all_times else 9999

print(f"\n   総リクエスト数: {len(all_results)}")
print(f"   総合成功率: {total_success_rate:.1f}%")
print(f"   総合平均レスポンス: {avg_time:.0f}ms")

# POST（注文）だけの統計
post_results = [r for r in all_results if r["method"] == "POST"]
post_ok = [r for r in post_results if r["success"]]
post_times = [r["time_ms"] for r in post_ok]
if post_times:
    print(f"\n   📝 注文API (POST) 統計:")
    print(f"      成功率: {len(post_ok)/len(post_results)*100:.1f}%")
    print(f"      平均: {statistics.mean(post_times):.0f}ms")

print("\n" + "-" * 65)
if total_success_rate >= 99 and avg_time < 2000:
    print("✅ 判定: 本番運用OK！")
    print("   金曜深夜のピーク時間でも安定稼働が見込めます")
elif total_success_rate >= 95 and avg_time < 3000:
    print("⚠️ 判定: 条件付きOK")
    print("   ピーク時に若干の遅延がありますが運用可能です")
elif total_success_rate >= 90:
    print("⚠️ 判定: 要注意")
    print("   大規模店舗では改善を検討してください")
else:
    print("❌ 判定: 要改善")
    print("   本番運用前にインフラ強化が必要です")

print("\n✨ テスト完了！")
