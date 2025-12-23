import requests
import time
import concurrent.futures
import statistics

BASE_URL = "https://web-production-d70f.up.railway.app"

def test_endpoint(name, url):
    start = time.time()
    try:
        resp = requests.get(url, timeout=10)
        elapsed = (time.time() - start) * 1000
        return {"name": name, "status": resp.status_code, "time_ms": elapsed, "success": resp.status_code < 400}
    except Exception as e:
        return {"name": name, "status": 0, "time_ms": 0, "success": False, "error": str(e)}

print("=" * 50)
print("🔍 基本エンドポイントテスト")
print("=" * 50)

endpoints = [
    ("Health", f"{BASE_URL}/health"),
    ("Admin", f"{BASE_URL}/admin.html"),
    ("Tables API", f"{BASE_URL}/api/tables"),
    ("Menu API", f"{BASE_URL}/api/menu"),
    ("Sessions API", f"{BASE_URL}/api/sessions/active"),
]

for name, url in endpoints:
    r = test_endpoint(name, url)
    icon = "✅" if r["success"] else "❌"
    print(f"{icon} {name}: {r['status']} - {r['time_ms']:.0f}ms")

print("\n" + "=" * 50)
print("🚀 同時接続テスト (20ユーザー)")
print("=" * 50)

def user_request(i):
    results = []
    for url in [f"{BASE_URL}/api/tables", f"{BASE_URL}/api/menu", f"{BASE_URL}/api/sessions/active"]:
        results.append(test_endpoint(f"U{i}", url))
    return results

all_results = []
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
    futures = [ex.submit(user_request, i) for i in range(20)]
    for f in concurrent.futures.as_completed(futures):
        all_results.extend(f.result())
total = time.time() - start

ok = [r for r in all_results if r["success"]]
times = [r["time_ms"] for r in ok]

print(f"総リクエスト: {len(all_results)}")
print(f"成功率: {len(ok)/len(all_results)*100:.1f}%")
print(f"スループット: {len(all_results)/total:.1f} req/sec")
if times:
    print(f"平均: {statistics.mean(times):.0f}ms / 最大: {max(times):.0f}ms")

print("\n" + "=" * 50)
print("💪 ストレステスト (5秒)")
print("=" * 50)

results = []
start = time.time()
while time.time() - start < 5:
    results.append(test_endpoint("S", f"{BASE_URL}/api/tables"))

ok = [r for r in results if r["success"]]
times = [r["time_ms"] for r in ok]
print(f"リクエスト数: {len(results)}")
print(f"成功率: {len(ok)/len(results)*100:.1f}%")
print(f"スループット: {len(results)/5:.1f} req/sec")
if times:
    print(f"平均: {statistics.mean(times):.0f}ms")

print("\n✨ 完了！")
