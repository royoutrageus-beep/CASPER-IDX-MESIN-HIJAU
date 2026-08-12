# CASPER v3.1 → v4.0 — apa yang diperbaiki

Ringkas: **satu file engine ditulis ulang**, UI menyesuaikan. Backup versi lama
ada di `casper_engine_v3_backup.py` dan `casper_app_v2_backup.py` — kalau ada
yang nggak sreg, tinggal balikin.

---

## 1. Bug hitungan yang beneran salah (bukan selera)

| # | Bug | Akibatnya di layar | Fix |
|---|---|---|---|
| 1 | `rsi_wilder` pakai `dn.replace(0, np.nan)` | saham yang 14 hari nggak pernah turun dapat **RSI = NaN**, bukan 100 → justru saham paling kuat kebuang dari zona RSI | RSI = 100 kalau nggak ada down-day, 0 kalau nggak ada up-day |
| 2 | `score`, `mesin_score`, `iq_score` isinya sama | korelasi **0.89 / 0.98 / 0.96** — tiga kolom, satu informasi. `rvol` dihitung 2×, trend 2× | `iq_score` = alpha lintas saham; `mesin_score` = kualitas eksekusi (korelasi turun ke **0.16**) |
| 3 | `rvol` = volume bar berjalan ÷ rata-rata **sehari penuh** | jam 10 pagi RVOL selalu kelihatan kecil → nyaris nggak ada yang lolos `RVOL ≥ 1.5` | penyebut diskalakan ke porsi sesi bursa yang udah lewat (`porsi_sesi()`) |
| 4 | `turnover` pakai **mean** 20 hari | 1 hari pump bikin saham tipis kelihatan likuid | ganti **median** |
| 5 | `vol_regime` bandingin EWMA-var sama akar rata-rata EWMA-var **yang sama** | dua-duanya gerak bareng → `SPIKE` nyaris nggak pernah nyala | EWMA λ0.94 vs realized σ 60 hari |
| 6 | `scan()` **crash** `KeyError: 'score'` kalau nol saham lolos | tiap kali Yahoo ngambek, app mati dengan error yang nggak nyambung | balikin DataFrame kosong berkolom lengkap + exception `DataKosong` yang jelas |
| 7 | TP/SL nggak di-snap fraksi harga IDX | muncul TP `3.612` padahal tick di harga segitu Rp10 | `tick_size()` 1/2/5/10/25 sesuai Peraturan BEI II-A |
| 8 | `rr` **diklaim** 1.9, nggak pernah dihitung | R:R di layar nggak ada hubungannya sama TP/SL yang dipasang | R:R dihitung dari TP & SL yang benar-benar dipakai |
| 9 | Tanggal bar data nggak pernah dicek | data basi/libur tetap dicap tanggal hari ini → evaluasi T+1/T+3 ngukur hari yang salah | kolom `data_date` + `bar` (TUTUP / BERJALAN / BASI), dipakai juga sebagai basis evaluasi |
| 10 | Dedup jurnal **di-bypass diam-diam** kalau baca Google Sheets gagal | `jurnal_sinyal.csv` lo isinya **1264 baris = 316 saham × 4 duplikat persis** | gagal baca = **batal nulis**, bukan tulis ulang semuanya |
| 11 | Kelly aktif dari **10 sampel** | di n=10, standard error win-rate ±16 poin — angka Kelly-nya noise yang dipoles | minimal **30 sampel** |
| 12 | `PERIODE = "1y"` tapi mode Swing/Bagger pakai MA200 | MA200 cuma punya ~50 bar riwayat | `PERIODE = "2y"`, minimal 200 bar per saham |

> Sudah gue cek langsung di `jurnal_sinyal.csv` lo: 1264 baris, tiap saham
> muncul **persis 4×** dengan angka identik. Itu bug #10.

---

## 2. Kenapa Telegram isinya itu-itu aja

Akar masalahnya bukan Telegram-nya. v3.1 nge-scan **KEADAAN**, bukan **KEJADIAN**:

> "harga di atas MA, RSI di zona, di atas VWAP"

Keadaan kayak gitu bertahan **berminggu-minggu**. Jadi saham yang sama lolos
filter tiap 15 menit, tiap hari, sampai trend-nya patah. Dari 316 saham yang
lolos filter, cuma **7 saham** yang dapat BUY (PKPK, AUTO, RBMS, MMIX, BKDP,
OASA, VERN) — dan ketujuhnya dikirim ulang tiap siklus.

Tiga perbaikan:

1. **Sinyal jadi EVENT.** Yang dikirim cuma yang kejadiannya masih fresh
   (default ≤ 3 bar):
   - `BREAKOUT 🚀` — close tembus Donchian ceiling **+ RVOL ≥ 1.5**
   - `GOLDEN CROSS ✨` — EMA cepat nyilang EMA lambat
   - `RECLAIM PIVOT 🎯` — close balik ke atas pivot setelah ≥ 3 bar di bawah
   - pola candle bullish **dengan** konteks trend + volume + di atas pivot

   > Ada jebakan halus di sini: `b & ~b.shift(1).fillna(False)` di pandas itu
   > **diam-diam sama dengan `b`** — `shift()` pada dtype bool balikin dtype
   > object, dan `~True` di object jadi `-2` yang truthy. Jadi "event" balik
   > lagi jadi "keadaan" tanpa error apa pun. Gue kena ini pas nulis v4 dan
   > baru ketahuan setelah ngitung distribusi jarak antar cross (median 1 bar
   > — mustahil). Sekarang di-`astype(bool)` di `bar_sejak_nyala()`.

2. **Cooldown per ticker + event.** Disimpan di `casper_terkirim.json`.
   Ticker + event yang sama nggak dikirim ulang dalam 20 jam.

3. **Telegram DIAM kalau nggak ada yang baru.** v3.1 punya fallback
   "tidak ada BUY — top skor:" yang justru ngirim 5 saham teratas tiap
   siklus — sumber spam terbesar. Sekarang nggak ada sinyal = nggak ada pesan.

Diuji: scan pertama kirim 7 sinyal, scan kedua (data sama) kirim **0** —
persis yang diharapkan.

---

## 3. Formula dari buku yang dikawinkan

**"151 Trading Strategies"** (Kakushadze & Serur, 2018), bagian 3 — Stocks:

| Bab | Formula | Dipakai jadi |
|---|---|---|
| 3.1 (eq. 268–269) | `R^risk.adj = R^mean / σ`, formation T + skip S | faktor `f_mom` |
| 3.4 | ranking σ 126 hari, rendah = bagus | faktor `f_lowvol` |
| 3.7 (eq. 278–281) | momentum dari **residual** regresi ke pasar | faktor `f_resmom` |
| 3.9 (eq. 292–294) | return di-demean lintas cluster | faktor `f_meanrev` |
| 3.11–3.13 (eq. 321–324) | single / two / three MA + stop Δ2% | event `GOLDEN CROSS`, kolom `exit_2pct` |
| 3.14 (eq. 325–328) | pivot `C=(H+L+C)/3`, `R=2C−L`, `S=2C−H` | event `RECLAIM PIVOT` + level TP/SL |
| 3.15 (eq. 329–331) | Donchian channel | event `BREAKOUT` |
| **3.6 / 3.20 (eq. 276–277)** | **demeaned rank**: `s_Ai = rank(f_Ai) − mean(rank)`, `s_i = (1/F) Σ s_Ai` | **cara gabung semua faktor** |

Yang paling penting justru **eq. 276–277**. Bobot lama `2+2+2+1+2+1` itu
ngarang, dan bisa dipenuhi 100% sama saham gorengan ATR 14% (lihat MMIX dan
RBMS di jurnal lo — dua-duanya dapat score 9.0). Demeaned rank itu kebal
outlier: yang dibandingin **peringkat**, bukan nilai mentah.

**`f_resmom` adalah yang paling relevan buat IDX.** Kalau IHSG lagi rally,
hampir semua saham momentumnya positif — v3.1 nggak bisa bedain *"saham ini
kuat"* dari *"pasarnya lagi naik"*. Makanya sinyalnya numpuk dan seragam.
Catatan jujur: buku pakai 3 faktor Fama-French (MKT/SMB/HML); IDX nggak punya
SMB/HML siap pakai, jadi di sini cuma 1 faktor pasar (IHSG). Lebih lemah dari
di buku, tapi jauh lebih baik daripada nggak sama sekali.

**Dari poster candlestick & support-resistance:**
- deteksi pola candle (engulfing, hammer, marubozu, morning/evening star,
  three white soldiers, piercing, dark cloud, harami, doji) — dengan syarat
  konteks, bukan cuma bentuk. Hammer tanpa penurunan sebelumnya cuma
  "candle berekor" dan nggak berarti apa-apa
- fase Wyckoff (Akumulasi / Mark-Up / Distribusi / Mark-Down) → kolom `fase`
- "breakout dengan volume besar lebih valid" → breakout tanpa volume masuk
  jurnal tapi **nggak** memicu BUY

---

## 4. Yang ketahuan pas ngerakit: dua aturan buku saling bentrok

Aturan 3.14 eq. 328 bilang **"likuidasi long kalau P ≥ R"**.
Aturan 3.15 eq. 331 bilang **"masuk long kalau P menembus ceiling"**.

Digabung mentah-mentah, syarat pertama **ngebunuh 100% breakout** — soalnya
breakout itu *artinya* harga lagi di atas resistance. Di funnel kelihatan
jelas: 7 breakout masuk, 0 lolos. Sekarang aturan pivot cuma dipakai buat
sinyal non-breakout.

Ini contoh kenapa panel funnel di bawah itu ada.

---

## 5. Fitur baru: panel "Kenapa segini"

Tab baru yang nunjukin **gerbang mana yang nutup**:

```
               syarat            lolos sendiri  kumulatif  dipangkas
   event fresh & kuat                       20         20          0
          alpha >= 70                       61         11          9   <-- biang
           trend naik                       76         10          1
       di atas VWAP20                      123         10          0
          RVOL >= 1.5                       52          6          4
           R:R >= 1.5                      175          4          2
```

Plus tier **NYARIS** — saham yang gagal cuma di **satu** syarat, lengkap sama
syarat mana yang kurang. Jadi "nol sinyal" berhenti jadi misteri.

---

## 6. Cara pakai

```bash
streamlit run casper_app.py                      # UI
python casper_engine.py --all --auto-mode --tele # CLI
python casper_engine.py --demo --mode Momentum   # tes tanpa jaringan
python casper_engine.py --all --tele --paksa-tele  # kirim top-8 walau nggak baru
```

Parameter baru: `--min-harga`, `--fresh` (umur maks event dalam bar),
`--paksa-tele`. Di UI semuanya ada di sidebar.

---

## 7. PR: bersihin jurnal lama

`jurnal_sinyal.csv` lo punya 4× duplikat dari bug #10. Statistik win-rate
apa pun yang dihitung dari situ **salah** — N-nya 4× lebih besar dari
observasi yang sebenarnya, jadi confidence interval-nya kelihatan sempit
padahal enggak.

Cara paling aman:

```python
import pandas as pd
j = pd.read_csv("jurnal_sinyal.csv")
j.drop_duplicates(["date", "ticker", "mode"]).to_csv("jurnal_sinyal.csv", index=False)
```

Skema kolom v4 beda dari v3, jadi engine bakal otomatis mengarsipkan file
lama ke `jurnal_sinyal_lama.csv` saat penulisan pertama. Aman.

---

## 8. Yang BELUM gue kerjain (biar jelas batasnya)

- **Belum di-backtest.** Semua di atas itu perbaikan *kebenaran hitungan* dan
  *desain sinyal*, bukan bukti profit. Tab "Bukti Statistik" sekarang bisa
  kelompokkan per `event` — itu jalan buat ngebuktiin sendiri apakah
  `BREAKOUT` beneran lebih baik dari `GOLDEN CROSS`. Butuh beberapa minggu
  jurnal bersih dulu.
- **Cluster mean-reversion masih 1 cluster** (seluruh universe). Buku 3.9.1
  bilang idealnya per sektor. Butuh data klasifikasi sektor IDX — belum ada
  di folder.
- **`f_mom` dan `f_resmom` berkorelasi tinggi** (0.6–0.95). Wajar, residual
  momentum emang versi bersih dari momentum. Bobot `f_mom` sengaja diturunin
  ke 0.7 biar versi bersihnya yang nyetir, tapi ini pilihan, bukan hasil
  optimasi.
- **Bobot faktor belum dioptimasi.** Sengaja. Optimasi bobot tanpa
  out-of-sample test cuma bikin overfit yang kelihatan meyakinkan.
