"""候補単価選択UI（FastAPI + Jinja2）。

ローカル単一ユーザー向けの軽量UI。サーバーは編集中の作業コピー（working_rows）を
メモリに保持し、保存時のみ layer_mapping_approved.csv に書き出す。
元の layer_mapping(.updated).csv は上書きしない。

注: 本ファイルでは `from __future__ import annotations` を使わない。FastAPI が
ルート関数の型注釈（Request 等）を実オブジェクトとして解決できるようにするため。
"""

import copy
import os
from datetime import datetime

from . import layer_mapping as lmap
from . import mapping_ui_models as m


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class MappingStore:
    """編集セッションの状態（メモリ保持）。"""

    def __init__(self, out_dir: str, tax_rate: float = None):
        self.out_dir = out_dir
        from . import settings as _tx
        self.tax_rate = _tx.normalize_rate(tax_rate)
        self.reload()

    def reload(self):
        self.state = m.load_state(self.out_dir)
        # 作業コピーと、差分基準のベースライン
        self.working_rows = copy.deepcopy(self.state["mapping_rows"])
        self.baseline_rows = copy.deepcopy(self.state["mapping_rows"])
        self.selections: dict[str, dict] = {}

    def _state_view(self):
        # working_rows を反映した state を返す（詳細表示用）
        v = dict(self.state)
        v["mapping_rows"] = self.working_rows
        return v

    def row(self, layer_name: str):
        return next((r for r in self.working_rows if r.get("layer_name", "") == layer_name), None)

    def update_row(self, layer_name: str, fields: dict):
        r = self.row(layer_name)
        if r is None:
            return
        for k in lmap.MAPPING_FIELDS:
            if k == "layer_name":
                continue
            if k in fields and fields[k] is not None:
                r[k] = str(fields[k])
        # 手入力した単価は manual として残す（item 6）
        if (fields.get("manual_unit_price", "") or "").strip():
            r["pricing_mode"] = "manual"


def create_app(out_dir: str, tax_rate: float = None):
    from fastapi import FastAPI, Request, Form
    from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    here = os.path.dirname(os.path.abspath(__file__))
    templates = Jinja2Templates(directory=os.path.join(here, "templates"))

    app = FastAPI(title="steel-estimator mapping UI")
    app.mount("/static", StaticFiles(directory=os.path.join(here, "static")), name="static")
    app.state.store = MappingStore(out_dir, tax_rate)

    def store() -> MappingStore:
        return app.state.store

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        st = store()
        data = m.dashboard_data(st._state_view(), st.tax_rate)
        return templates.TemplateResponse(request, "mapping_dashboard.html", {
            "request": request, "d": data, "out_dir": out_dir,
            "rerun_cmd": m.rerun_command(out_dir),
        })

    @app.get("/layers", response_class=HTMLResponse)
    def layers(request: Request):
        st = store()
        rows = []
        for r in st.working_rows:
            name = r.get("layer_name", "")
            sugg = st.state["suggestions_by_layer"].get(name)
            rows.append({
                "row": r,
                "needs_price": m._needs_price(r),
                "match_level": (sugg or {}).get("match_level", ""),
            })
        return templates.TemplateResponse(request, "mapping_layers.html", {
            "request": request, "rows": rows, "out_dir": out_dir,
        })

    @app.get("/layers/{layer_name}", response_class=HTMLResponse)
    def layer_detail(request: Request, layer_name: str, show_processed: int = 0):
        st = store()
        detail = m.layer_detail(st._state_view(), layer_name,
                                show_processed=bool(show_processed), tax_rate=st.tax_rate)
        if detail["row"] is None:
            return PlainTextResponse(f"レイヤーが見つかりません: {layer_name}", status_code=404)
        return templates.TemplateResponse(request, "mapping_layer_detail.html", {
            "request": request, "d": detail, "layer_name": layer_name,
            "fields": lmap.MAPPING_FIELDS, "show_processed": bool(show_processed),
            "out_dir": out_dir,
        })

    @app.post("/layers/{layer_name}")
    async def edit_layer(request: Request, layer_name: str):
        form = await request.form()
        store().update_row(layer_name, dict(form))
        return RedirectResponse(f"/layers/{_enc(layer_name)}", status_code=303)

    @app.post("/layers/{layer_name}/apply-suggestion")
    async def apply_suggestion(request: Request, layer_name: str):
        form = await request.form()
        spec_key = form.get("spec_key", "")
        st = store()
        cand = _find_candidate(st, layer_name, spec_key)
        r = st.row(layer_name)
        if cand is not None and r is not None:
            new_row = m.apply_candidate_to_row(r, cand)
            st.update_row(layer_name, new_row)
            st.selections[layer_name] = m.selection_meta(cand)
        return RedirectResponse(f"/layers/{_enc(layer_name)}", status_code=303)

    @app.post("/save", response_class=HTMLResponse)
    def save(request: Request):
        st = store()
        res = m.save_approved(out_dir, st.working_rows, st.baseline_rows,
                              st.selections, _now())
        # 保存後はベースラインを現状に更新（次回保存の差分起点）
        st.baseline_rows = copy.deepcopy(st.working_rows)
        st.selections = {}
        return templates.TemplateResponse(request, "mapping_dashboard.html", {
            "request": request, "d": m.dashboard_data(st._state_view(), st.tax_rate),
            "out_dir": out_dir, "rerun_cmd": m.rerun_command(out_dir),
            "saved": res,
        })

    @app.post("/rerun-estimate", response_class=PlainTextResponse)
    def rerun_estimate():
        rhino_csv = os.path.join(out_dir, "rhino_objects.csv")
        approved = os.path.join(out_dir, m.APPROVED_NAME)
        if not os.path.exists(approved):
            return PlainTextResponse("先に保存してください（approvedが未作成）。", status_code=400)
        if not os.path.exists(rhino_csv):
            return PlainTextResponse(
                "rhino_objects.csv が out-dir にありません。次のコマンドを手動実行してください:\n"
                + m.rerun_command(out_dir), status_code=200)
        from . import rhino_run
        cost = os.path.join(out_dir, "cost_items.csv")
        res = rhino_run.run_rhino_estimate(
            rhino_csv_path=rhino_csv, mapping_path=approved,
            cost_items_path=cost if os.path.exists(cost) else None,
            out_dir=out_dir, now_str=_now())
        store().reload()
        s = res["stats"]
        return PlainTextResponse(
            f"再見積完了。概算合計(税別) ¥{s['estimated_total']:,} / "
            f"未設定 {s['unmapped']} / needs_review {s['needs_review']}\n"
            f"report: {res['report_path']}")

    @app.get("/download/layer_mapping_approved.csv")
    def download():
        p = os.path.join(out_dir, m.APPROVED_NAME)
        if not os.path.exists(p):
            return PlainTextResponse("approvedが未作成です。先に保存してください。", status_code=404)
        return FileResponse(p, media_type="text/csv", filename=m.APPROVED_NAME)

    return app


def _enc(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def _find_candidate(st: MappingStore, layer_name: str, spec_key: str):
    # まず提案（suggestion）から
    sugg = st.state["suggestions_by_layer"].get(layer_name)
    if sugg and (sugg.get("suggested_spec_key") == spec_key or not spec_key):
        return sugg
    # 次に同カテゴリ候補から spec_key 一致
    for c in st.state["candidates"]:
        if c.get("spec_key") == spec_key:
            return c
    return sugg


def run_server(out_dir: str, host: str = "127.0.0.1", port: int = 8765,
               tax_rate: float = None, public_reference: str = ""):
    import uvicorn
    import os
    import shutil
    # 公開参考価格フォルダが指定され、out-dir に未配置なら参照用にコピー（表示・候補用）
    if public_reference and os.path.isdir(public_reference):
        for name in ("public_plate_reference_prices.csv", "public_shape_reference_prices.csv"):
            src = os.path.join(public_reference, name)
            dst = os.path.join(out_dir, name)
            if os.path.exists(src) and not os.path.exists(dst):
                os.makedirs(out_dir, exist_ok=True)
                shutil.copy2(src, dst)
        print(f"  公開参考価格を参照: {public_reference}")
        print("  ※ 公開用参考価格。実取引価格ではありません。")
    app = create_app(out_dir, tax_rate)
    print(f"[mapping-ui] http://{host}:{port}  (out-dir: {out_dir})")
    print("  Ctrl+C で停止します。保存先は layer_mapping_approved.csv（元mappingは上書きしません）。")
    print("  単価は税抜で保存。税込はダッシュボードに参考表示します。")
    uvicorn.run(app, host=host, port=port, log_level="warning")
