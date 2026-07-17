# -*- coding: utf-8 -*-
"""
Penerjemah JSON -> Secrets Streamlit
====================================
1. Pastikan gsheet_creds.json ada di folder ini
2. Jalankan:  python konversi_secrets.py
3. Salin SEMUA output yang muncul di layar
4. Paste ke dashboard Streamlit Cloud: app lo -> Settings -> Secrets -> Save
"""
import json
import os

if not os.path.exists("gsheet_creds.json"):
    print("[!] gsheet_creds.json tidak ditemukan di folder ini.")
    print("    Download dulu key JSON service account dari Google Cloud,")
    print("    rename jadi gsheet_creds.json, taruh di sini.")
    raise SystemExit(1)

d = json.load(open("gsheet_creds.json"))

print("# ==== SALIN MULAI DARI SINI ====")
print("[gcp_service_account]")
for k, v in d.items():
    v = str(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    print(f'{k} = "{v}"')
print("# ==== SAMPAI SINI ====")
