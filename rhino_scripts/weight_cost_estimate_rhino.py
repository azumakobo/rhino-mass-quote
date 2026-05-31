"""[互換用シム] 旧名 weight_cost_estimate_rhino.py → quote_estimate_rhino.py に移行。

Quote（概算見積）は `quote_estimate_rhino.py` が本体です。本ファイルは旧名互換のため、
新ファイルの main() を呼ぶだけにしています。新規利用は quote_estimate_rhino.py を使ってください。
"""

import os
import sys


def _load_quote():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        here = os.getcwd()
    if here not in sys.path:
        sys.path.insert(0, here)
    import quote_estimate_rhino as quote
    return quote


def running_in_rhino():
    return _load_quote().running_in_rhino()


def main():
    return _load_quote().main()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("[weight_cost_estimate_rhino→quote] " + str(e))
        raise SystemExit(1)
