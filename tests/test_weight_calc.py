"""重量計算の検証。既知の理論値・JIS近傍値と照合する。"""

import math

import pytest

from steel_estimator import estimate as est
from steel_estimator.models import MaterialCategory as C, MaterialRequest


def test_round_bar_known():
    # φ50, L=1000mm, 7.85 → V=π/4·5²·100 cm³ = 1963.5 cm³ → 15.41 kg
    w = est.weight_round_bar_kg(50, 1000)
    expected = math.pi / 4 * (5 ** 2) * 100 * 7.85 / 1000
    assert w == pytest.approx(expected, rel=1e-6)
    assert w == pytest.approx(15.41, abs=0.05)


def test_round_pipe_known():
    # φ48.6 t2.3 L6000 → STK相当。単重 ≈ 2.63 kg/m → 6m で ≈ 15.8 kg
    w = est.weight_round_pipe_kg(48.6, 2.3, 6000)
    assert w == pytest.approx(15.77, abs=0.3)


def test_round_pipe_hollow_less_than_solid():
    solid = est.weight_round_bar_kg(60, 1000)
    pipe = est.weight_round_pipe_kg(60, 3, 1000)
    assert pipe < solid


def test_square_pipe_known():
    # □50×50×2.3 L6000。角部シャープの理論値 ≈ 3.445 kg/m → 6m で ≈ 20.67 kg。
    # JIS実値(角R考慮)は ≈ 3.34 kg/m=20.0kg で、本式は約3%過大評価（保守側）。
    w = est.weight_square_pipe_kg(50, 50, 2.3, 6000)
    assert w == pytest.approx(20.67, abs=0.2)


def test_plate_known():
    # PL 6×914×1829 → V=0.6×91.4×182.9 cm³ ×7.85 /1000
    w = est.weight_plate_kg(6, 914, 1829)
    expected = 0.6 * 91.4 * 182.9 * 7.85 / 1000
    assert w == pytest.approx(expected, rel=1e-6)
    assert w == pytest.approx(78.7, abs=0.5)


def test_estimate_weight_dispatch():
    # 丸パイプ
    req = MaterialRequest(material_category=C.ROUND_PIPE,
                          diameter_mm=48.6, thickness_mm=2.3, length_mm=6000)
    assert est.estimate_weight_kg(req) == pytest.approx(15.77, abs=0.3)

    # アングルは v1 では None（JIS表必要）
    req2 = MaterialRequest(material_category=C.ANGLE,
                           width_mm=50, height_mm=50, thickness_mm=6, length_mm=5500)
    assert est.estimate_weight_kg(req2) is None

    # 鉄板（plate_width/height）
    req3 = MaterialRequest(material_category=C.PLATE,
                           thickness_mm=6, plate_width_mm=914, plate_height_mm=1829)
    assert est.estimate_weight_kg(req3) == pytest.approx(78.7, abs=0.5)


def test_density_argument():
    # SUS304 密度 ≈ 7.93 を渡すと鉄(7.85)より重い
    w_steel = est.weight_plate_kg(6, 1000, 1000)
    w_sus = est.weight_plate_kg(6, 1000, 1000, density_g_cm3=7.93)
    assert w_sus > w_steel


def test_price_summary():
    s = est.summarize_prices([100, 200, 300])
    assert s["n"] == 3
    assert s["median"] == 200
    assert s["mean"] == pytest.approx(200)
    assert s["max"] == 300
    assert s["min"] == 100
