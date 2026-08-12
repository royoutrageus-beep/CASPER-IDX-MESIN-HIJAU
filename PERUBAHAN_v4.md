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

---
---

# v4.0 → v4.1 — BSJP, bandarmologi Arjum, proyeksi Bagger, jadwal EOD

File baru: `casper_arjum.py`, `.github/workflows/casper_eod.yml`, `.gitignore` (diupdate).

## 1. Mode BSJP (Beli Sore Jual Pagi)

Horizonnya **semalam**, jadi hampir semua yang cocok buat Swing malah nggak relevan
di sini. Yang dibedain:

| Aspek | Mode lain | BSJP |
|---|---|---|
| Faktor | momentum 3 bln, low-vol, residual momentum | **closing strength**, **edge overnight historis**, **bandar**, volume |
| Event yang dianggap kuat | breakout, golden cross, reclaim pivot | cuma **`TUTUP KUAT 🌆`** (close di ⅓ atas range + RVOL ≥ 1.5 + di atas VWAP) |
| Stop | pivot S / Donchian floor, maks 3 ATR | **di bawah low hari ini** — kalau besok buka di bawah situ, premisnya batal |
| Target | resistance struktural ≥ 1R, atau 2R | pivot R besok, atau 2R |

Faktor `f_overnight` itu **risk-adjusted** (eq. 269 dari buku, dipinjam ke konteks
overnight): `mean(overnight) / std(overnight)` selama 120 hari. Tanpa dibagi std,
saham yang gap-nya gede tapi acak bakal ngalahin yang naik tipis tapi konsisten —
padahal buat strategi yang diulang tiap hari, konsistensi itu yang bayar.

Kolom baru: `close_str`, `ov_menang_pct` (berapa % hari overnight-nya positif),
`ov_rata_pct`.

> **Event multi-hari tetap dicatat di mode BSJP tapi nggak pernah "kuat".** Breakout
> Donchian 40 bar itu setup berminggu-minggu — nggak ada artinya buat posisi yang
> dijual besok jam 9.

## 2. Bandarmologi — `casper_arjum.py`

Skema API-nya **nggak di-hardcode**. Semua di `arjum_config.json`: base URL, cara
auth, path endpoint, dan **peta field pakai daftar alias**. Adapter nyocokin alias
pertama yang ketemu, jadi kalau nama field di API-nya `netval` bukan `net_value`,
yang lo ubah cukup JSON-nya.

Udah gue uji pakai server tiruan yang sengaja pakai nama field beda
(`kode`/`bc`/`bval`/`sval`/`netval`/`asing_net`) — kepetakan semua, otomatis.

```bash
python casper_arjum.py --tulis-konfig                 # bikin arjum_config.json
python casper_arjum.py --cek --tanggal 2026-08-12     # diagnosa skema response
```

`--cek` itu **langkah pertama** waktu nyambungin API: dia nampilin field apa aja yang
beneran ada di response, mana yang kepetakan, mana yang belum. Kalau ada field wajib
yang nggak ketemu, adapter **melempar error yang nyebutin nama field aslinya** —
bukan diam-diam ngasih NaN.

Yang dihitung: `net_bandar_jt`, `hari_net_buy` (konsistensi > besaran),
`konsentrasi_top5` (beli numpuk di sedikit broker = akumulasi terarah; nyebar rata =
ritel), `foreign_net_jt`.

**Fallback:** kalau key belum ada / API lagi mati, `proxy_dari_ohlcv()` ngitung
Chaikin Money Flow + kemiringan A/D + OBV. Kolom **`bandar_sumber` selalu keisi**
(`Arjum ✅` / `proksi OHLCV ⚠️`) — soalnya dua-duanya ngisi kolom yang sama, dan
tanpa penanda gampang banget salah sangka lagi lihat data broker padahal cuma
tebakan dari harga & volume.

Kalau Arjum cuma nyakup sebagian universe (saham tipis sering nggak ada broker
summary-nya), sisanya **ditambal proksi**, dan skornya di-rank **terpisah per
sumber** — net value rupiah (miliaran) dan CMF (−1..1) nggak boleh masuk satu
ranking, angkanya nggak sebanding.

Response di-cache per tanggal di `cache_arjum/` — data EOD nggak berubah setelah
bursa tutup, jadi scan berulang nggak ngabisin kuota API.

## 3. Proyeksi Bagger

`proyeksi_bagger()` — **block bootstrap**, blok 20 hari, 1500 simulasi.

- **Kenapa block, bukan bootstrap biasa:** return saham punya volatility clustering
  (hari ribut ngumpul sama hari ribut). Ngacak return satu-satu ngerusak struktur itu
  dan bikin sebarannya kelihatan jauh lebih adem dari kenyataan.
- **Kenapa bukan rumus lognormal:** return IDX ekor gemuk. Asumsi normal ngecilin
  peluang kejadian ekstrem — dua-duanya, yang bikin kaya dan yang bikin nyangkut.

Output: `proj_p25` / `proj_p50` / `proj_p75` (% 12 bulan), `p_2x`, `p_setengah`.
Cuma dihitung buat top-40 alpha (mahal), dan cuma di mode Bagger.

> Ini **bukan ramalan**. Bacanya: *"kalau perilaku harga ke depan mirip 2 tahun
> kebelakang, sebarannya segini."* Jarak p25→p75 yang lebar itu bukan model jelek —
> itu ketidakpastian yang emang segitu. Kalau fundamental atau likuiditasnya berubah,
> angka ini nggak berlaku sama sekali.

## 4. Scan EOD + jadwal otomatis

```bash
python casper_engine.py --all --eod --tele          # 3 horizon sekaligus
python casper_engine.py --all --eod --eod-mode BSJP Swing --tele
```

Satu pesan Telegram, dipisah per horizon: **BSJP** (beli sore ini), **Swing** (beli
besok), **Bagger** (kandidat panjang + proyeksi). Kalau satu horizon nggak ada yang
lolos, pesannya nyebutin **gerbang mana yang paling banyak nyaring** — bukan cuma
"nggak ada sinyal".

**Jadwalnya lewat GitHub Actions**, bukan Task Scheduler Windows — jalan walau laptop
mati, punya internet penuh, secrets dikelola GitHub.

- `schedule`: **16:30 WIB** (09:30 UTC) Senin–Jumat + **cadangan 19:30 WIB** kalau
  yang sore gagal atau data Yahoo masih basi. Dedup jurnal + cooldown Telegram yang
  mastiin nggak ada kiriman dobel.
  *Sengaja 16:30, bukan 16:00: bursa tutup 15:50 dan data Yahoo butuh waktu settle.*
- `workflow_dispatch`: tombol **Run workflow** di tab Actions — bisa dari HP.
- Kalau job-nya **gagal**, lo dikabarin di Telegram. Job gagal diam-diam itu bahaya:
  lo kira "hari ini pasar sepi" padahal scan-nya nggak pernah jalan.

Secrets yang perlu diisi di **Settings → Secrets and variables → Actions**:

| Secret | Wajib? | Isinya |
|---|---|---|
| `TELE_TOKEN` | ✅ | token bot Telegram |
| `TELE_CHAT_ID` | ✅ | chat id lo |
| `ARJUM_KEY` | opsional | API key Arjum (kosong → proksi OHLCV) |
| `ARJUM_BASE_URL` | opsional | kalau base URL-nya beda dari default |
| `GCP_SERVICE_ACCOUNT` | opsional | isi `gsheet_creds.json` **utuh** — biar jurnal & memori anti-spam awet |

## 5. `.gitignore` — WAJIB dicek sebelum push

`arjum_config.json` isinya **API key lo**. Udah gue tambahin ke `.gitignore` bareng
`casper_terkirim.json` dan `cache_arjum/`. Pastiin file `.gitignore` yang baru ikut
ke-commit **sebelum** lo bikin `arjum_config.json`.

## 6. Batas yang perlu diinget

- **Skema Arjum masih tebakan.** Path endpoint (`/broker-summary`, `/netflow`,
  `/eod`) dan nama header (`X-API-Key`) belum diverifikasi ke dokumentasi asli.
  Jalanin `--cek` dulu; kalau nggak cocok, benerin `arjum_config.json` — atau kirim
  docs-nya ke gue, gue sesuaikan.
- **Belum ada bukti BSJP profit di IDX.** Yang gue bikin itu mesin ukurnya. Tab
  Bukti Statistik bisa dikelompokkan per `event`, jadi setelah beberapa minggu jurnal
  bersih lo bisa lihat sendiri apakah `TUTUP KUAT` beneran ngasih edge overnight.
- **`ov_menang_pct` dihitung dari open Yahoo.** Open IDX di Yahoo kadang nggak persis
  harga pembukaan pre-opening. Kalau Arjum punya OHLC resmi, mendingan pindah ke situ.

---
---

# v4.1 → v4.2 — adapter Arjum disesuaikan ke skema ASLI

Setelah dapat dokumentasi endpoint aslinya, adapter ditulis ulang. Tiga hal
berubah secara struktural — dan satu di antaranya bikin salah satu metrik di v4.1
ternyata **angka kosong**.

## 1. 🔴 Koreksi penting: `total net value` itu SELALU NOL

v4.1 ngitung `net_bandar_jt = sum(net_value)` seluruh broker. Begitu lihat skema
aslinya, ketahuan itu **nggak ada artinya**:

> Tiap lembar yang dibeli seseorang, dijual orang lain. Jadi jumlah `nval` seluruh
> broker itu **nol menurut definisi**. Kalau angkanya keluar bukan nol, itu semata
> karena datanya kepotong `broker_limit` — dan besarnya cuma nunjukin seberapa
> banyak yang kepotong, bukan seberapa kuat bandarnya.

Diganti metrik yang beneran punya arah:

| Kolom | Artinya |
|---|---|
| `akum_jt` | total `nval` broker yang **net beli** = berapa banyak barang pindah ke pihak pengumpul |
| `konsentrasi_top5` | share 5 broker pembeli terbesar dari total beli. Tinggi = akumulasi terarah; rendah = nyebar rata (ciri ritel) |
| `dominasi_1` | share broker pembeli #1 dari total akumulasi |
| `tiket_beli_jt` | **`bval / bfrq`** = rata-rata nilai per transaksi beli. Institusi nyicil gede, ritel nyicil receh — sidik jari yang susah dipalsu |
| `foreign_net_jt` | net asing, dari panggilan **terpisah** `flow=F` |
| `broker_top` | nama broker pembeli terbesar |

**Net asing butuh request kedua.** Di `flow=all`, broker asing dan domestik campur
dan sum-nya tetap nol — nggak ada cara misahin dari satu response. Jadi `flow=F`
dipanggil terpisah. Bisa dimatiin lewat `bandar_asing=False` kalau mau hemat kuota.

## 2. `code` itu PATH parameter → scan dua tahap

`GET /api/broker-summary/{code}` — satu request = **satu saham**. Nggak ada endpoint
"semua saham sekaligus". Nembak ~700 ticker tiap scan = 700 request, kena rate limit
dan lama banget.

Solusinya:

```
Tahap 1 (murah) : SELURUH universe di-rank pakai OHLCV + proksi CMF/A/D
Tahap 2 (mahal) : cuma `bandar_top` kandidat teratas yang ditembak ke Arjum
```

Default `bandar_top=40` → 40 request (80 kalau net asing ikut), bukan 700.
Sisanya tetap kepakai lewat proksi, dan `bandar_sumber` per baris ngasih tau mana
yang dapat data broker asli.

> **Sub-bug yang ketemu pas nguji ini:** ranking tahap-1 awalnya selalu pakai bobot
> `FAKTOR`, padahal mode BSJP punya `FAKTOR_BSJP` sendiri. Akibatnya yang ditembak
> ke Arjum itu kandidat versi Swing, sementara yang nangkring di atas setelah
> `f_bandar` masuk malah saham lain — top-10 hasil akhir semuanya "proksi".
> Sekarang tahap-1 pakai bobot mode yang lagi jalan: **10/10 teratas** dapat data asli.

Response di-cache per (kode, rentang tanggal, flow). Scan kedua di hari yang sama =
**0 request tambahan**. Sudah diuji.

## 3. Response bersarang + field induk

Response bukan list datar, tapi objek:

```json
{ "stock_code": "BBCA", "latest_date": "2026-07-24", "flow": "all",
  "brokers": [ {"broker_code":"BK","bval":...,"sval":...,"nval":...,
                "nvol":...,"bfrq":...,"sfrq":...}, ... ] }
```

`stock_code` dan `latest_date` ada di **top level**, bukan di tiap baris broker —
jadi ditarik turun ke tiap baris oleh adapter. Alias field udah disesuaikan ke nama
asli (`nval`, `bval`, `sval`, `nvol`, `bfrq`, `sfrq`, `broker_code`, `broker_name`)
— `--cek` mengkonfirmasi **BELUM kepetakan: []`, semua kena.

## 4. Cek sambungan

```bash
python casper_arjum.py --health                    # /api/health
python casper_arjum.py --cek --code BBCA           # diagnosa skema
python casper_arjum.py --cek --code BBCA --flow F  # cek response net asing
```

## 5. Endpoint lain yang BELUM dipakai (kandidat upgrade berikutnya)

Dari daftar 10 endpoint, empat ini kelihatan berharga tapi gue belum punya skema
response-nya:

| Endpoint | Kenapa menarik |
|---|---|
| `/api/history/{code}` | OHLCV resmi IDX — bisa **gantiin Yahoo Finance**. Yahoo itu sumber semua masalah data basi/partial bar/glitch harga di dokumen ini |
| `/api/seasonal/{code}` | Seasonality win rate — persis yang dibutuhin faktor `f_overnight` di BSJP, dan pasti lebih akurat dari open Yahoo |
| `/api/screener/latest` | Kalau ini balikin **seluruh universe sekaligus**, tahap-1 nggak perlu Yahoo sama sekali dan scan jadi jauh lebih cepat |
| `/api/broker-accumulation/{code}` | Akumulasi historis **per hari** — bikin metrik konsistensi (`hari_net_buy`) yang di v4.1 gugur bisa balik dengan benar |

Kirim contoh response empat itu, gue sambungin.

---

# v4.2 → v4.2.1 — perbaikan crash Streamlit + tes UI headless

## Bug: `StreamlitAPIException` pas scan kedua

```python
st.session_state.update(..., auto_mode_on=auto_mode_on, ...)   # ❌
```

`auto_mode_on` itu **key milik widget** (`st.toggle(..., key="auto_mode_on")`).
Streamlit ngelarang nimpa `session_state` buat key yang udah ke-bind ke widget.

Yang bikin ini nyebelin: di Streamlit Cloud **pesan aslinya disensor**
("*The original error message is redacted to prevent data leaks*"), jadi yang
kelihatan cuma traceback tanpa sebab. Baris `auto_mode_on=auto_mode_on` juga
nggak keliatan salah kalau cuma dibaca sekilas.

**Fix:** nilai toggle-nya nggak perlu disalin sama sekali — `auto_scan()` udah
baca `st.session_state["auto_mode_on"]` langsung dari widget-nya.

## `use_container_width` udah lewat tanggal matinya

Streamlit ngewarning: *"`use_container_width` will be removed after
2025-12-31"* — dan sekarang udah Agustus 2026. Masih jalan, tapi tinggal nunggu
versi berikutnya. 10 pemakaian diganti ke `width="stretch"`, dan
`requirements.txt` dinaikin ke `streamlit>=1.49` (parameter `width` butuh versi
segitu).

## File baru: `uji_app.py` — smoke test UI headless

```bash
python uji_app.py
```

Bug di atas **nggak mungkin ketangkep** sama `pyflakes` atau tes engine — dia cuma
muncul waktu Streamlit beneran jalan, dan **cuma di rerun kedua** (run pertama
widget-nya belum ke-instantiate). Jadi sekarang ada tes yang ngejalanin app-nya
beneran lewat `streamlit.testing.v1.AppTest`:

- render awal + scan otomatis
- **rerun kedua** ← inilah yang nangkep bug ini
- ganti mode ke BSJP / Intraday / Bagger
- ngitung error box & warning yang muncul di layar

Sumber data dipatch ke simulasi sebelum app di-import, jadi tesnya nggak nembak
Yahoo maupun Arjum — cepat dan bisa jalan offline.

Udah gue verifikasi tesnya **beneran gagal** waktu bug-nya sengaja dibalikin —
tes yang nggak pernah merah itu nggak ngebuktiin apa-apa.

> Saran: tambahin `python uji_app.py` ke workflow GitHub Actions sebagai step
> sebelum scan, biar app yang rusak ketahuan sebelum ke-deploy ke Streamlit Cloud.

---

# v4.2.1 → v4.2.2 — kode yang sama harus jalan di laptop DAN di Cloud

## Kesalahan gue di v4.2.1

Gue ganti semua `use_container_width=True` jadi `width="stretch"` terus naikin
`requirements.txt` ke `streamlit>=1.49`. Itu **jawaban yang salah**: Streamlit
Cloud jalan di versi baru, laptop lo di versi lama, dan naikin requirements nggak
bikin Streamlit di laptop lo ikut naik. Hasilnya:

```
TypeError: ButtonMixin.button() got an unexpected keyword argument 'width'
```

Dan ternyata migrasinya **nggak serentak per widget**: `st.dataframe` dapat
`width` jauh lebih dulu daripada `st.button`.

## Ada jebakan kedua yang lebih halus

Ngecek "apakah parameter `width` ada" itu **nggak cukup**. Di Streamlit 1.40
`st.dataframe` udah punya `width` — tapi tipenya `int | None`, **lebar dalam
pixel**. Ngoper `"stretch"` ke situ salah tipe dan bisa gagal diam-diam.

Jadi shim `lebar()` di `casper_app.py` ngecek nilai yang **DITERIMA**, bukan nama
parameternya: baca anotasi tipe + docstring, cari kata `stretch`. Hasil deteksi
di-cache (`lru_cache`), jadi cuma sekali per proses.

Diverifikasi di dua versi beneran, bukan diteori:

| | Streamlit 1.40.0 | Streamlit 1.61.1 |
|---|---|---|
| `st.button` | `use_container_width=True` | `width="stretch"` |
| `st.dataframe` | `use_container_width=True` | `width="stretch"` |
| `st.selectbox` | *(nggak ngoper apa-apa)* | `width="stretch"` |

`requirements.txt` dibalikin ke `streamlit>=1.37`.

## Bonus: kotak merah "No secrets found" di laptop

Ketahuan pas nguji di 1.40 — UI-nya penuh kotak merah:

```
No secrets found. Valid paths for a secrets.toml file are:
  ~/.streamlit/secrets.toml, ./.streamlit/secrets.toml
```

Sebabnya: di Streamlit lama, sekadar **nyentuh** `st.secrets` waktu file-nya nggak
ada itu **ngerender kotak merah di UI** sebelum exception-nya dilempar. Jadi
`try/except` yang udah ada di `ambil_config_tele()` / `ambil_key()` **nggak nolong**
— kotaknya udah terlanjur muncul. Di laptop yang cuma pakai `config_tele.json`
(tanpa `secrets.toml`), tiap scan bikin 2-4 kotak merah padahal semuanya normal.

Fix: `_secrets_tersedia()` ngecek keberadaan file-nya **dulu**, sebelum `st.secrets`
disentuh sama sekali.

## Kenapa ini kelewat di v4.2.1

`uji_app.py` cuma gue jalanin di container (Streamlit 1.61). Sekarang tesnya
dijalanin di **dua versi**:

```bash
python uji_app.py                        # versi yang keinstall
/path/venv-lama/bin/python uji_app.py    # versi lama, buat cek kompatibilitas
```

Bikin venv pembanding sekali aja:

```bash
python -m venv venv-lama
venv-lama/bin/pip install "streamlit==1.40.0" pandas numpy pytz
```

Pelajarannya: **tes yang cuma jalan di satu environment nggak ngebuktiin
kompatibilitas.** Bug ini nggak keliatan di container, dan cuma muncul di laptop
lo — persis lubang yang ditinggalin sama nguji cuma di satu tempat.
