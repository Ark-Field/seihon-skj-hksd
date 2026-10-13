from flask import Flask, request, jsonify, render_template_string
import pandas as pd
import io
from datetime import datetime, timedelta

app = Flask(__name__)

# アップロード用HTML画面（UI）
INDEX_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>製本管理業務 - 工程管理予定表システム</title>
    <style>
        body { font-family: sans-serif; margin: 40px; background-color: #f9f9f9; color: #333; }
        h1 { color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px; }
        .card { background: #fff; padding: 25px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
        label { font-weight: bold; display: block; margin-top: 15px; }
        input[type="file"], input[type="number"] { margin-top: 5px; margin-bottom: 10px; display: block; width: 100%; max-width: 400px; padding: 6px; }
        button { background-color: #28a745; color: white; border: none; padding: 12px 24px; font-size: 16px; border-radius: 4px; cursor: pointer; margin-top: 20px; }
        button:hover { background-color: #218838; }
        .note { font-size: 12px; color: #666; margin-top: 2px; }
    </style>
</head>
<body>
    <h1>製本管理業務 工程管理予定表システム</h1>
    <div class="card">
        <form action="/upload" method="post" enctype="multipart/form-data">
            <h3>1. 各種CSVデータの選択</h3>
            
            <label>CSV① 受注データ（必須）:</label>
            <input type="file" name="csv1" accept=".csv" required>
            <div class="note">※受注日、受注番号、得意先、書名1、受注部数、納期日付、順、工程、実行工程、人数、所要時間（30分単位）</div>
            
            <label>CSV② 休暇シフトデータ（任意）:</label>
            <input type="file" name="csv2" accept=".csv">
            <div class="note">※基本稼働時間から差し引く休暇情報が含まれるCSV</div>
            
            <label>CSV③ 機械稼働NGデータ（任意）:</label>
            <input type="file" name="csv3" accept=".csv">
            <div class="note">※機械の停止・メンテナンス予定が含まれるCSV</div>

            <h3>2. 基本設定パラメータ</h3>
            <label>基本人員数（人）:</label>
            <input type="number" name="base_staff" value="10" required>

            <label>完成期日（納期の何日前までに完了させるか）:</label>
            <input type="number" name="deadline_days" value="1" required>

            <button type="submit">スケジュールを計算・生成する</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        f1 = request.files.get('csv1')
        f2 = request.files.get('csv2')
        f3 = request.files.get('csv3')
        base_staff = int(request.form.get('base_staff', 10))
        deadline_days = int(request.form.get('deadline_days', 1))

        if not f1:
            return "CSV①（受注データ）は必須です。", 400

        # CSV①（受注データ）の読み込み
        df_order = pd.read_csv(io.StringIO(f1.read().decode('utf-8')))
        
        # CSV②（休暇シフト）の読み込み（任意）
        df_shift = pd.DataFrame()
        if f2 and f2.filename:
            df_shift = pd.read_csv(io.StringIO(f2.read().decode('utf-8')))

        # CSV③（機械NG）の読み込み（任意）
        df_ng = pd.DataFrame()
        if f3 and f3.filename:
            df_ng = pd.read_csv(io.StringIO(f3.read().decode('utf-8')))

        # ★【ご要望対応】「工程」が空欄・空白・NaNの行を完全に自動除外する
        if '工程' in df_order.columns:
            df_order = df_order.dropna(subset=['工程'])
            df_order = df_order[df_order['工程'].astype(str).str.strip() != '']
            df_order = df_order[df_order['工程'].astype(str).str.lower() != 'nan']

        if df_order.empty:
            return "<h3>エラー:</h3><p>有効な「工程」データが存在する行が見つかりませんでした。</p><br><a href='/'>戻る</a>", 400

        # 工程の順番（順）を守るために受注番号と順でソート
        df_order = df_order.sort_values(by=["受注番号", "順"])

        scheduled_results = []
        daily_summary = {}

        for _, row in df_order.iterrows():
            customer = str(row.get("得意先", ""))
            item_name = str(row.get("書名1", ""))
            seq = row.get("順", 1)
            process = str(row.get("工程", ""))
            staff_needed = int(row.get("人数", 1))
            duration_slots = float(row.get("所要時間（30分単位）", 2))
            hours = duration_slots * 0.5  # 30分単位を時間に換算（1コマ30分 = 0.5時間）
            due_date_str = str(row.get("納期日付", ""))

            # 納期から逆算した完成期日（納期の●日前）の算出
            try:
                due_date = datetime.strptime(due_date_str.strip(), "%Y-%m-%d")
                target_date = due_date - timedelta(days=deadline_days)
                target_date_str = target_date.strftime("%Y-%m-%d")
            except:
                target_date_str = due_date_str

            # 予定結果の格納（1タスク単位）
            scheduled_results.append({
                "日付": target_date_str,
                "順番": seq,
                "案件名": item_name,
                "顧客名": customer,
                "工程": process,
                "人員": staff_needed,
                "時間": hours
            })

            # 日ごとの人員・時間集計
            if target_date_str not in daily_summary:
                daily_summary[target_date_str] = {"total_staff": staff_needed, "total_hours": hours}
            else:
                daily_summary[target_date_str]["total_staff"] += staff_needed
                daily_summary[target_date_str]["total_hours"] += hours

        # 出力用HTMLの構築
        result_html = """
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <title>工程管理予定表 結果</title>
            <style>
                body { font-family: sans-serif; margin: 30px; background-color: #fdfdfd; color: #333; }
                table { width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 30px; }
                th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
                th { background-color: #007bff; color: white; }
                h2 { color: #333; border-bottom: 2px solid #007bff; padding-bottom: 5px; }
                a { display: inline-block; margin-bottom: 20px; text-decoration: none; background: #6c757d; color: white; padding: 8px 15px; border-radius: 4px; }
                a:hover { background: #5a6268; }
            </style>
        </head>
        <body>
            <a href="/">← 戻る（再アップロード）</a>
            <h2>📋 詳細スケジュール</h2>
            <table>
                <tr><th>日付</th><th>順番</th><th>案件名</th><th>顧客名</th><th>工程</th><th>人員</th><th>時間</th></tr>
        """
        for r in scheduled_results:
            result_html += f"<tr><td>{r['日付']}</td><td>{r['順番']}</td><td>{r['案件名']}</td><td>{r['顧客名']}</td><td>{r['工程']}</td><td>{r['人員']}人</td><td>{r['時間']}時間</td></tr>"
        
        result_html += """
            </table>
            <h2>📊 日ごとの人員・時間合計 ＆ 過不足チェック</h2>
            <table>
                <tr><th>日付</th><th>合計人員</th><th>合計時間</th><th>過不足ステータス</th></tr>
        """
        for d, vals in daily_summary.items():
            diff = base_staff - vals['total_staff']
            status = f"余裕あり (+{diff}人)" if diff >= 0 else f"不足（{abs(diff)}人超過）"
            status_color = "green" if diff >= 0 else "red"
            result_html += f"<tr><td>{d}</td><td>{vals['total_staff']}人</td><td>{vals['total_hours']}時間</td><td style='color:{status_color}; font-weight:bold;'>{status}</td></tr>"

        result_html += "</table></body></html>"
        return result_html

    except Exception as e:
        return f"<h3>エラーが発生しました:</h3><p>{str(e)}</p><br><a href='/'>戻る</a>", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)