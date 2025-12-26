import requests
import time
import concurrent.futures
import statistics

BASE_URL = "https://web-production-d70f.up.railway.app"

def test_endpoint(name, url):
    start = time.time()
    try:
        resp = requests.get(url, timeout=15)
        elapsed = (time.time() - start) * 1000
        return {"name": name, "status": resp.status_code, "time_ms": elapsed, "success": resp.status_code < 400}
    except Exception as e:
        return {"name": name, "status": 0, "time_ms": 0, "success": False, "error": str(e)}

print("=" * 60)
print("🏢 大規模店舗テスト（20卓・60キャスト・20スタッフ）")
print("=" * 60)

# シナリオ: スタッフ20人 + 注文画面20卓 = 40同時接続
STAFF_COUNT = 20  # 管理画面
TABLE_COUNT = 20  # 注文画面
TOTAL_USERS = STAFF_COUNT + TABLE_COUNT

print(f"\n📊 シミュレーション: {TOTAL_USERS}同時接続")
print(f"   - スタッフ（管理画面）: {STAFF_COUNT}人")
print(f"   - テーブル（注文画面）: {TABLE_COUNT}卓")

print("\n" + "=" * 60)
print("🚀 同時接続テスト")
print("=" * 60)

def staff_session(i):
    """スタッフ: 管理画面の操作"""
    results = []
    # テーブル一覧、オーダー一覧、セッション確認
    for url in [
        f"{BASE_URL}/api/tables",
        f"{BASE_URL}/api/orders",
        f"{BASE_URL}/api/sessions/active",
        f"{BASE_URL}/api/casts",
    ]:
        results.append(test_endpoint(f"Staff{i}", url))
    return results

def table_session(i):
    """テーブル: 注文画面の操作"""
    results = []
    # メニュー取得、テーブル情報
    for url in [
        f"{BASE_URL}/api/menu",
        f"{BASE_URL}/api/tables",
    ]:
        results.append(test_endpoint(f"Table{i}", url))
    return results

all_results = []
start = time.time()

with concurrent.futures.ThreadPoolExecutor(max_workers=TOTAL_USERS) as ex:
    futures = []
    # スタッフ
    for i in range(STAFF_COUNT):
        futures.append(ex.submit(staff_session, i))
    # テーブル
    for i in range(TABLE_COUNT):
        futures.append(ex.submit(table_session, i))
    
    for f in concurrent.futures.as_completed(futures):
        all_results.extend(f.result())

total = time.time() - start

ok = [r for r in all_results if r["success"]]
fail = [r for r in all_results if not r["success"]]
times = [r["time_ms"] for r in ok]

print(f"\n📊 結果サマリー:")
print(f"   総リクエスト: {len(all_results)}")
print(f"   成功: {len(ok)} ({len(ok)/len(all_results)*100:.1f}%)")
print(f"   失敗: {len(fail)} ({len(fail)/len(all_results)*100:.1f}%)")
print(f"   総実行時間: {total:.2f}秒")
print(f"   スループット: {len(all_results)/total:.1f} req/sec")

if times:
    print(f"\n⏱️ レスポンス時間:")
    print(f"   平均: {statistics.mean(times):.0f}ms")
    print(f"   最小: {min(times):.0f}ms")
    print(f"   最大: {max(times):.0f}ms")
    sorted_times = sorted(times)
    p95 = sorted_times[int(len(sorted_times)*0.95)] if len(sorted_times) > 20 else max(times)
    print(f"   95%タイル: {p95:.0f}ms")

if fail:
    print(f"\n❌ 失敗詳細:")
    for f in fail[:5]:
        print(f"   {f['name']}: {f.get('error', 'Unknown')}")

print("\n" + "=" * 60)
print("💪 ピーク負荷テスト（全員が同時に更新ボタン押す）")
print("=" * 60)

def burst_request(i):
    return test_endpoint(f"Burst{i}", f"{BASE_URL}/api/orders")

burst_results = []
start = time.time()

with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
    futures = [ex.submit(burst_request, i) for i in range(50)]
    for f in concurrent.futures.as_completed(futures):
        burst_results.append(f.result())

burst_time = time.time() - start
burst_ok = [r for r in burst_results if r["success"]]
burst_times = [r["time_ms"] for r in burst_ok]

print(f"\n📊 50同時リクエスト結果:")
print(f"   成功率: {len(burst_ok)/len(burst_results)*100:.1f}%")
print(f"   実行時間: {burst_time:.2f}秒")
if burst_times:
    print(f"   平均: {statistics.mean(burst_times):.0f}ms")
    print(f"   最大: {max(burst_times):.0f}ms")

print("\n" + "=" * 60)
print("🎯 総合評価")
print("=" * 60)

success_rate = len(ok) / len(all_results) * 100
avg_time = statistics.mean(times) if times else 9999

if success_rate >= 99 and avg_time < 2000:
    print("\n✅ 大規模店舗運用: OK!")
    print("   20卓・60キャスト・20スタッフに対応可能")
elif success_rate >= 95 and avg_time < 3000:
    print("\n⚠️ 大規模店舗運用: 注意")
    print("   混雑時に若干の遅延の可能性あり")
else:
    print("\n❌ 大規模店舗運用: 要改善")
    print("   スケールアップを検討してください")

print("\n✨ テスト完了！")
