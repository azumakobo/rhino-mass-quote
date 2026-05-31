# rhino-mass-quote

> Rhino commands for material mass calculation and rough metal quote estimation, designed for artists, fabrication studios, and public art production workflows.

Rhinoコマンドで使える、鋼材の重量計算・概算見積ツール。

このリポジトリには2つの完成品がある:

| コマンド | 用途 |
|---|---|
| **Mass** | 素材密度から重量を計算する（金属・木材・樹脂等） |
| **Quote** | 体積→重量→公開参考単価で概算材料費を出す（金属） |

**重量だけ知りたい → Mass / 概算材料費を出したい → Quote**

> 研究・制作補助・OSS的な位置づけのツールです（収益化しません）。

---

## なぜRhinoコマンドなのか

開発当初はブラウザで動く Web UI（mapping-ui）、Rhino内フローティングパネル、  
CSV承認フローなども実装した。しかし、**Rhinoでモデリング中に他のUIを操作する**のは  
実務上不自然で、手順が多すぎた。

最終的に「重量を知りたい」「金額を確認したい」の2つのシーンに絞り、  
**RhinoコマンドバーにAliasを打つだけで完結する**2つの小さなツールに収束した。

経緯の詳細は [`docs/development-log.md`](docs/development-log.md) を参照。

---

## インストール

```bash
pip install -e ".[dev]"
```

Rhinoコマンド（Mass / Quote）だけ使うなら pip インストールは不要。  
以下の「RhinoScripts配置」と「Alias登録」だけ行えばよい。

---

## Alias 登録（Mass / Quote をコマンドバーから起動）

### 1. RhinoScripts へファイルをコピー

```bash
cp rhino_scripts/mass_rhino.py              ~/Documents/RhinoScripts/
cp rhino_scripts/mass_core_for_rhino.py     ~/Documents/RhinoScripts/
cp rhino_scripts/quote_estimate_rhino.py    ~/Documents/RhinoScripts/
cp rhino_scripts/steel_estimate_core_for_rhino.py  ~/Documents/RhinoScripts/
```

### 2. Rhinoceros > Preferences > Aliases に登録

| Alias名 | コマンドマクロ |
|---|---|
| `Mass` | `! _-RunPythonScript "~/Documents/RhinoScripts/mass_rhino.py"` |
| `Quote` | `! _-RunPythonScript "~/Documents/RhinoScripts/quote_estimate_rhino.py"` |

パスは環境に合わせて変更すること。

詳細・よくあるエラー → [`docs/rhino-command-usage.md`](docs/rhino-command-usage.md)

---

## Mass — 重量計算

選択したRhinoオブジェクトの体積から重量を計算する。

**対応素材:** 鉄 / ステンレス / アルミ / 木材 / 合板 / MDF / アクリル / 樹脂 / カスタム

**操作:** オブジェクト選択 → `Mass` → 素材選択 → （任意）kg単価入力 → 重量・材料費を表示

- UserTextへの書き込みなし、CSV保存なし、確認ダイアログなし
- 前回値は `~/Documents/RhinoScripts/mass_settings.json` に記録
- 標準ライブラリのみ（Rhino 8 ScriptEditor で動作）

---

## Quote — 概算見積

体積から重量を出し、公開用参考価格の円/kgを掛けて概算材料費を出す。

**操作フロー:**
1. オブジェクト選択 → `Quote`
2. **重量計算用素材を選択**（鉄 / ステンレス / アルミ）
3. **概算用単価カテゴリを選択**（板 t6 / 板 t9 / 角パイプ / 丸パイプ / FB等）
4. **見積モードを選択:**
   - 通常見積（推奨）: 公開参考単価 × 安全係数 1.2
   - 安全側見積: 保守値 × 安全係数 1.2
   - 手入力: ユーザー入力値をそのまま使用（安全係数なし）
5. 税抜・税込の概算金額を表示 → UserTextに書き込み

設定は `~/Documents/RhinoScripts/quote_settings.json` に記録。

---

## 価格データの扱い（重要）

`public_reference_data/` に含まれる価格データ:

- 元データは実見積PDF（231ファイル）由来だが、**公開版では取引先名・見積日・PDF名・個別明細を削除済み**
- 価格は **10円単位切り上げ** の集約値
- 通常見積・安全側見積には **安全係数 1.2 を適用**
- 安全側単価は中央値の **1.3〜2.0 倍にclamp**（外れ値抑制）
- **これは実取引価格ではない**
- 市況・ロット・地域・加工条件・仕入れ先によって変動する
- **正式発注前には必ず各業者へ見積を取り直すこと**
- このツールの価格は研究・制作初期の概算用であり、見積書の代替にはならない

詳細 → [`docs/security-and-public-data.md`](docs/security-and-public-data.md)

---

## データの分離方針

| 区分 | 場所 | Git |
|---|---|---|
| 実PDF・実DB・実CSV・レポート | `data/`, `quotes/`, `akiyama_quotes/` | **管理外** |
| 公開用の匿名化・集約・丸め済み参考単価 | `public_reference_data/` | 管理対象 |
| 例示用サンプル | `samples/` | 管理対象 |
| 認証情報 | `credentials.json`, `token.json` | **管理外** |

公開前安全性チェック:
```bash
python -m steel_estimator.cli release-audit
```

---

## その他のツール（補助・参考）

### レイヤーパネル（Rhino内UI）

`rhino_scripts/steel_estimate_rhino_panel.py` を ScriptEditor で Run すると、  
レイヤー別の体積・重量・金額パネルを表示できる（参考ツール・実験的）。

### CLI（CSV経由の見積）

```bash
# デモ（実データ不要）
python -m steel_estimator.cli run-demo --out-dir ./demo_output --tax-rate 0.10

# Rhino CSV → 公開参考単価で一括見積
python -m steel_estimator.cli estimate-public-rhino \
  --rhino-csv ./samples/rhino_objects_demo.csv --out-dir ./public_demo_output
```

### 主なCLIコマンド

- `run-demo` — 公開参考単価だけで概算見積のデモ
- `estimate-public-rhino` — Rhino CSV → 公開参考単価で一括見積
- `audit-public-data` — 公開参考価格の混入チェック
- `release-audit` — 公開前監査一括実行

---

## ドキュメント

| ファイル | 内容 |
|---|---|
| [`docs/development-log.md`](docs/development-log.md) | 開発経緯（Web UI → Rhinoコマンドへの方針転換） |
| [`docs/final-architecture.md`](docs/final-architecture.md) | Mass / Quote の最終仕様・アーキテクチャ |
| [`docs/security-and-public-data.md`](docs/security-and-public-data.md) | 公開参考価格の安全性・免責 |
| [`docs/rhino-command-usage.md`](docs/rhino-command-usage.md) | Alias登録・手順・よくあるエラー |
| [`docs/release-checklist.md`](docs/release-checklist.md) | GitHub公開前チェックリスト |
| [`docs/data-security.md`](docs/data-security.md) | データ保護方針（旧） |
| [`docs/rhino-command-registration.md`](docs/rhino-command-registration.md) | Alias登録詳細（旧） |

---

## テスト

```bash
python -m pytest tests/ -q
```

306 tests（2026-05-31）。

---

## ライセンス

MIT License

価格データ（`public_reference_data/`）は匿名化・集約・丸め処理済みの参考値であり、  
実取引価格ではありません。利用は自己責任で。
