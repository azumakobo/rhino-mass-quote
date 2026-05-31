"""layer_mapping の雛形生成・非破壊更新のテスト。"""

from steel_estimator import layer_mapping as lmap


SUMMARY = [
    {"layer_name": "鉄板6mm", "suggested_calc_type": "area_to_weight",
     "suggested_material_category": "plate", "suggested_spec_text": "鉄板6mm",
     "suggested_thickness_mm": "6", "suggested_diameter_mm": "",
     "suggested_width_mm": "", "suggested_height_mm": "", "warning": ""},
    {"layer_name": "角パイプ_50", "suggested_calc_type": "curve_length_to_stock",
     "suggested_material_category": "square_pipe", "suggested_spec_text": "角パイプ_50",
     "suggested_thickness_mm": "", "suggested_diameter_mm": "",
     "suggested_width_mm": "50", "suggested_height_mm": "", "warning": ""},
]


def test_init_mapping_all_layers():
    """init-layer-mapping で全レイヤーの雛形を生成できる（必須3）。"""
    rows = lmap.init_mapping_from_summary(SUMMARY)
    assert len(rows) == 2
    names = [r["layer_name"] for r in rows]
    assert names == ["鉄板6mm", "角パイプ_50"]
    # suggested_* が初期値に流用される
    assert rows[0]["calc_type"] == "area_to_weight"
    assert rows[0]["thickness_mm"] == "6"
    assert rows[0]["price_unit"] == "kg"
    # 確定でない旨が notes に明記される
    assert "確認" in rows[0]["notes"]
    # 全行に MAPPING_FIELDS が揃う
    for r in rows:
        assert set(lmap.MAPPING_FIELDS).issubset(r.keys())


def test_update_mapping_preserves_existing_adds_new():
    """update-layer-mapping は既存を壊さず新規だけ追加（必須4）。"""
    existing = [{
        **{f: "" for f in lmap.MAPPING_FIELDS},
        "layer_name": "鉄板6mm", "calc_type": "area_to_weight",
        "unit_price": "150", "thickness_mm": "6", "notes": "ユーザー確定済み",
    }]
    summary_with_new = SUMMARY + [{
        "layer_name": "丸パイプ手すり", "suggested_calc_type": "curve_length_to_stock",
        "suggested_material_category": "round_pipe", "suggested_spec_text": "丸パイプ手すり",
        "suggested_thickness_mm": "", "suggested_diameter_mm": "42.7",
        "suggested_width_mm": "", "suggested_height_mm": "", "warning": "",
    }]
    merged, added = lmap.update_mapping(existing, summary_with_new)
    # 既存行は値そのまま保持
    teppan = [r for r in merged if r["layer_name"] == "鉄板6mm"][0]
    assert teppan["unit_price"] == "150"
    assert teppan["notes"] == "ユーザー確定済み"
    # 新規だけ追加される
    assert "角パイプ_50" in added
    assert "丸パイプ手すり" in added
    assert "鉄板6mm" not in added
    assert {r["layer_name"] for r in merged} == {"鉄板6mm", "角パイプ_50", "丸パイプ手すり"}
