# -*- coding: utf-8 -*-
"""Smoke test UI headless — nangkep error yang cuma muncul pas Streamlit
beneran jalan (dan yang di Streamlit Cloud pesannya disensor).

Jalanin:  python uji_app.py
"""
import sys
import casper_engine as ce

# Ganti sumber data ke simulasi SEBELUM app di-import, biar tes nggak
# nembak Yahoo/Arjum. App pakai `import casper_engine as ce`, jadi dia
# dapat modul yang udah dipatch ini dari sys.modules.
_ASLI = ce.unduh_ohlcv
ce.unduh_ohlcv = lambda tickers, periode=ce.PERIODE: ce.data_demo(
    list(tickers)[:120])
ce.unduh_ihsg = lambda periode=ce.PERIODE: None
ce.get_market_regime = lambda close=None: (
    "Swing", 7500.0, 7400.0, 7300.0, "(tes) UPTREND")
ce.catat_jurnal = lambda df, path=ce.JURNAL: 0
ce.evaluasi_jurnal = lambda *a, **k: None
ce.kirim_tele = lambda *a, **k: False

from streamlit.testing.v1 import AppTest      # noqa: E402


def cek(at, label):
    if at.exception:
        print(f"❌ {label}")
        for e in at.exception:
            print("   ", str(e.value)[:400])
        return False
    print(f"✅ {label}"
          f" · error box: {len(at.error)} · warning: {len(at.warning)}"
          f" · dataframe: {len(at.dataframe)}")
    for e in at.error:
        print("    [error box]", str(e.value)[:200])
    return True


def main():
    ok = True
    at = AppTest.from_file("casper_app.py", default_timeout=180)
    at.run()
    ok &= cek(at, "render awal + scan otomatis")

    # rerun: inilah yang dulu meledak — nulis session_state buat key yang
    # udah ke-bind ke widget (`auto_mode_on`) baru kelihatan di run kedua
    at.run()
    ok &= cek(at, "rerun kedua (uji bentrok session_state vs widget)")

    for m in ("BSJP", "Intraday", "Bagger"):
        at.toggle[0].set_value(False)          # matiin Auto-Mode
        at.run()
        sel = [s for s in at.selectbox if "Mode sinyal" in (s.label or "")]
        if sel:
            sel[0].set_value(m)
            at.run()
            ok &= cek(at, f"mode {m}")

    # klik tab-tab: funnel, journal, bukti statistik
    at.run()
    ok &= cek(at, "render akhir")

    print("\n" + ("SEMUA LOLOS ✅" if ok else "ADA YANG GAGAL ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
