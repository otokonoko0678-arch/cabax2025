/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./static/admin.html",
    "./static/order.html",
    "./static/super-admin.html",
  ],
  // 監査済み: クラス名を変数で組み立てる箇所 (例 `bg-${x}-500`) は 0 件で、
  // 全 Tailwind クラスが完全な文字列としてファイルに現れるため content スキャンで
  // 全て検出される。動的クラスが見つかったらここに safelist を追加する。
  safelist: [],
  theme: {
    extend: {},
  },
  plugins: [],
};
