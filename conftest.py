"""pytest 収集前に .env を読み込む。

tests/test_scenarios.py の requires_api_key マーカーはモジュール読み込み時に
os.environ.get("ANTHROPIC_API_KEY") を評価する。.env はアプリ実行時は
python-dotenv 経由で読み込まれるが、pytest 実行時はシェルの環境変数を
そのまま見るだけなので、.env に書いてあってもここで読み込まない限り
「未設定」と判定されテストがスキップされ続ける。
"""
from dotenv import load_dotenv

load_dotenv()
