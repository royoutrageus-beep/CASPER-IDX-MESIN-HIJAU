# ═══════════════════════════════════════════════════════════════════
#  MESIN ENTRY v1.1 — Probabilistic Entry Timing Engine
#  Based on Kakushadze & Serur (2018) "151 Trading Strategies"
#  Primary recipes:
#    • Section 18.2 — ANN features (z-score normalized returns)
#    • Section 3.17 — KNN single-asset pattern matching
#    • Section 3.20 — Alpha combo (proper signal combination)
#  Supports: Scalping (5m) → Intraday (15-30m) → Swing (1h-1d) → Bagger (1wk)
#  Markets:  IDX (auto .JK), US, Crypto (auto -USD), FX (auto =X), Commodity
# ═══════════════════════════════════════════════════════════════════

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import pytz
import random
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────
def _get_secret(*names, default=""):
    for n in names:
        try:
            v = st.secrets.get(n, default)
            if v: return v
        except: pass
    return default

TOKEN   = _get_secret("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN")
CHAT_ID = _get_secret("TELEGRAM_CHAT_ID")
et_tz   = pytz.timezone('US/Eastern')

st.set_page_config(
    layout="wide",
    page_title="Mesin Entry v1.1",
    page_icon="🎯",
    initial_sidebar_state="collapsed"
)

# ─── MARKET AUTO-SUFFIX ────────────────────────────────────────────
MARKET_SUFFIX = {
    "IDX (Indonesia)":   ".JK",   # BBCA → BBCA.JK
    "US Stocks":         "",      # AAPL stays AAPL
    "Crypto":            "-USD",  # BTC → BTC-USD
    "FX / Forex":        "=X",    # EURUSD → EURUSD=X
    "Commodity":         "",      # GC=F, XAUUSD=X stays as-is
}

# ─── COMMODITY ALIAS MAP ──────────────────────────────────────────
# yFinance punya known issues dengan FX-style commodity spot (XAUUSD=X dll):
# data sub-hourly sering kosong walaupun ticker valid. Solusi: auto-remap ke
# futures equivalent (GC=F, SI=F, dll) yang DATA-NYA RELIABLE di yFinance.
COMMODITY_ALIAS = {
    # Precious metals
    "XAUUSD": "GC=F",   # Gold spot → Gold futures (yFinance reliable)
    "GOLD":   "GC=F",
    "XAGUSD": "SI=F",   # Silver spot → Silver futures
    "SILVER": "SI=F",
    "XPTUSD": "PL=F",   # Platinum
    "PLATINUM": "PL=F",
    "XPDUSD": "PA=F",   # Palladium
    # Energy
    "WTIUSD":  "CL=F",  # WTI Crude
    "USOIL":   "CL=F",
    "OIL":     "CL=F",
    "WTI":     "CL=F",
    "BCOUSD":  "BZ=F",  # Brent Crude
    "UKOIL":   "BZ=F",
    "BRENT":   "BZ=F",
    "NGAS":    "NG=F",  # Natural Gas
    "NATGAS":  "NG=F",
    "GASOIL":  "HO=F",  # Heating oil
    # Base metals
    "COPPER":  "HG=F",
    "HGUSD":   "HG=F",
    # Agriculturals
    "CORN":    "ZC=F",
    "WHEAT":   "ZW=F",
    "SOYBEAN": "ZS=F",
    "COFFEE":  "KC=F",
    "SUGAR":   "SB=F",
    "COCOA":   "CC=F",
    "COTTON":  "CT=F",
}


# ─── IDX TICKER UNIVERSE (981 stocks for multi-scan) ──────────────
IDX_TICKERS = [
    "AADI","AALI","ABBA","ABDA","ABMM","ACES","ACRO","ACST","ADCP","ADES",
    "ADHI","ADMF","ADMG","ADMR","ADRO","AEGS","AGAR","AGII","AGRO","AGRS",
    "AHAP","AIMS","AISA","AKKU","AKPI","AKRA","AKSI","ALDO","ALII","ALKA",
    "ALMI","ALTO","AMAG","AMAN","AMAR","AMFG","AMIN","AMMN","AMMS","AMOR",
    "AMRT","ANDI","ANJT","ANTM","APEX","APIC","APII","APLI","APLN","ARCI",
    "AREA","ARGO","ARII","ARKA","ARKO","ARMY","ARNA","ARTA","ARTI","ARTO",
    "ASBI","ASDM","ASGR","ASHA","ASII","ASJT","ASLI","ASLC","ASMI","ASPI",
    "ASPR","ASRI","ASRM","ASSA","ATAP","ATIC","ATLA","AUTO","AVIA","AWAN",
    "AXIO","AYAM","AYLS","BABA","BABP","BABY","BACA","BAIK","BAJA","BALI",
    "BANK","BAPA","BAPI","BATA","BATR","BAUT","BAYU","BBCA","BBHI","BBKP",
    "BBLD","BBMD","BBNI","BBRI","BBRM","BBSI","BBSS","BBTN","BBYB","BCAP",
    "BCIC","BCIP","BDKR","BDMN","BEBS","BEEF","BEER","BEKS","BELI","BELL",
    "BESS","BEST","BFIN","BGTG","BHAT","BHIT","BIAS","BIKA","BIKE","BIMA",
    "BINA","BINO","BIPI","BIPP","BIRD","BISI","BIWA","BJBR","BJTM","BKDP",
    "BKSL","BKSW","BLES","BLOG","BLTA","BLTZ","BLUE","BMAS","BMBL","BMHS",
    "BMRI","BMSR","BMTR","BNBA","BNBR","BNGA","BNII","BNLI","BOAT","BOBA",
    "BOGA","BOLA","BOLT","BOSS","BPFI","BPII","BPTR","BRAM","BREN","BRIS",
    "BRMS","BRNA","BRPT","BRRC","BSBK","BSDE","BSIM","BSML","BSSR","BSWD",
    "BTEK","BTEL","BTON","BTPN","BTPS","BUAH","BUDI","BUKA","BUKK","BULL",
    "BUMI","BUVA","BVIC","BWPT","BYAN","CAKK","CAMP","CANI","CARE","CARS",
    "CASA","CASH","CASS","CBDK","CBPE","CBRE","CBUT","CBMF","CCSI","CDIA",
    "CEKA","CENT","CFIN","CGAS","CHEK","CHEM","CHIP","CINT","CITA","CITY",
    "CLAY","CLEO","CLPI","CMNP","CMNT","CMPP","CMRY","CNKO","CNMA","CNTX",
    "COAL","COCO","COIN","COWL","CPIN","CPRI","CPRO","CRAB","CRSN","CSAP",
    "CSIS","CSMI","CSRA","CTBN","CTRA","CTTH","CUAN","CYBR","DAAZ","DADA",
    "DART","DATA","DAYA","DCII","DEAL","DEFI","DEPO","DEWA","DEWI","DFAM",
    "DGNS","DGWG","DGIK","DIGI","DILD","DIVA","DKFT","DKHH","DLTA","DMAS",
    "DMMX","DMND","DNAR","DNET","DOID","DOOH","DOSS","DPNS","DPUM","DRMA",
    "DSFI","DSNG","DSSA","DUCK","DUTI","DVLA","DWGL","DYAN","EAST","ECII",
    "EDGE","EKAD","ELIT","ELPI","ELSA","ELTY","EMAS","EMDE","EMTK","ENAK",
    "ENRG","ENVY","ENZO","EPAC","EPMT","ERAL","ERAA","ERTX","ESIP","ESSA",
    "ESTA","ESTI","ETWA","EURO","EXCL","FAPA","FAST","FASW","FILM","FIMP",
    "FIRE","FISH","FITT","FLMC","FOLK","FOOD","FORE","FORU","FPNI","FUJI",
    "FUTR","FWCT","GAMA","GDST","GDYR","GEMA","GEMS","GGRP","GGRM","GHON",
    "GIAA","GJTL","GLOB","GLVA","GMFI","GMTD","GOLF","GOLD","GOLL","GOOD",
    "GOTO","GPRA","GPSO","GRIA","GRPH","GRPM","GRII","GSMF","GTBO","GTRA",
    "GTSI","GULA","GUNA","GWSA","GZCO","HADE","HAIS","HAJJ","HALO","HATM",
    "HBAT","HDFA","HDIT","HEAL","HELI","HERO","HEXA","HGII","HILL","HITS",
    "HKMU","HMSP","HOKI","HOME","HOMI","HOPE","HOTL","HRME","HRTA","HRUM",
    "HUMI","HYGN","IATA","IBFN","IBOS","IBST","ICBP","ICON","IDEA","IDPR",
    "IFII","IFSH","IGAR","IIKP","IKAI","IKAN","IKBI","IKPM","IMAS","IMJS",
    "IMPC","INAF","INAI","INCF","INCI","INCO","INDF","INDO","INDR","INDS",
    "INDX","INDY","INET","INKP","INOV","INPC","INPP","INPS","INRU","INTA",
    "INTD","INTP","IOTF","IPAC","IPCC","IPCM","IPOL","IPPE","IPTV","IRRA",
    "IRSX","ISAP","ISAT","ISEA","ISSP","ITIC","ITMA","ITMG","JAAS","JARR",
    "JAST","JATI","JAVA","JAYA","JECC","JGLE","JIHD","JKON","JMAS","JPFA",
    "JRPT","JSKY","JSMR","JSPT","JTPE","KAEF","KAQI","KARW","KARY","KAST",
    "KAYU","KBAG","KBLI","KBLM","KBLV","KBRI","KDSI","KDTN","KEEN","KEJU",
    "KETR","KIAS","KICI","KIJA","KING","KINO","KIOS","KJEN","KKES","KKGI",
    "KLAS","KLBF","KLIN","KMDS","KMTR","KOBX","KOCI","KOIN","KOKA","KONI",
    "KOPI","KOTA","KPIG","KRAH","KRAS","KREN","KSIX","KUAS","LABA","LABS",
    "LAJU","LAND","LAPD","LCGP","LCKM","LEAD","LFLO","LIFE","LINK","LION",
    "LIVE","LMAS","LMPI","LMSH","LOPI","LPCK","LPGI","LPIN","LPKR","LPLI",
    "LPPF","LPPS","LRNA","LSIP","LTLS","LUCK","LUCY","MAAS","MABA","MADA",
    "MAGP","MAHA","MAIN","MANG","MAPA","MAPB","MAPI","MARI","MARK","MASA",
    "MASB","MAYA","MBAP","MBMA","MBSS","MBTO","MCAS","MCOL","MCOR","MDIA",
    "MDKA","MDKI","MDLA","MDLN","MDRN","MEDC","MEDS","MEGA","MEJA","MENN",
    "MERI","MERK","META","MFMI","MGNA","MGRO","MHKI","MICE","MIDI","MIKA",
    "MINA","MINE","MIRA","MITI","MKAP","MKPI","MKTR","MLBI","MLIA","MLPL",
    "MLPT","MMLP","MMIX","MNCN","MOLI","MORA","MPOW","MPMX","MPPA","MPRO",
    "MPXL","MRAT","MREI","MSIE","MSIN","MSJA","MSKY","MSTI","MTDL","MTEL",
    "MTFN","MTLA","MTMH","MTPS","MTRA","MTRN","MTSM","MTWI","MUTU","MYOH",
    "MYOR","MYTX","NAIK","NANO","NASA","NASI","NATO","NAYZ","NCKL","NELY",
    "NEST","NETV","NICE","NICK","NICL","NIKL","NINE","NIRO","NISP","NOBU",
    "NPGF","NRCA","NSSS","NTBK","NUSA","NZIA","OASA","OBAT","OBMD","OCAP",
    "OILS","OKAS","OLIV","OMED","OMRE","OPMS","PACK","PADA","PADI","PALM",
    "PAMG","PANI","PANR","PANS","PART","PBID","PBSA","PBRX","PCAR","PDES",
    "PDPP","PEGE","PEHA","PELI","PENT","PERW","PEVE","PGAS","PGEO","PGJO",
    "PGLI","PGUN","PICO","PIPA","PJAA","PJHB","PKPK","PLAN","PLAS","PLIN",
    "PMJS","PMMP","PMUI","PNBN","PNBS","PNGO","PNIN","PNLF","PNSE","POLA",
    "POLI","POLL","POLU","POLY","POOL","PORT","POSA","POWR","PPGL","PPRI",
    "PPRE","PPRO","PRAY","PRDA","PRIM","PSAB","PSAT","PSDN","PSGO","PSKT",
    "PSSI","PTBA","PTDU","PTIS","PTMP","PTMR","PTPP","PTPS","PTPW","PTRO",
    "PTSN","PTSP","PUDP","PURA","PURE","PURI","PWON","PYFA","PZZA","RAAM",
    "RAFI","RAJA","RALS","RANC","RATU","RBMS","RCCC","RDTX","REAL","RELF",
    "RELI","REPP","RGAS","RICY","RIGS","RIMO","RISE","RLCO","RMBA","RMKE",
    "RMKO","RMLP","ROCK","RODA","ROLI","RONY","ROTI","RSCH","RSGK","RUIS",
    "RUNS","SAFE","SAGE","SAGI","SAME","SAMF","SAMR","SAMP","SANO","SAPX",
    "SATU","SBAT","SBMA","SCCO","SCMA","SCNP","SCPI","SDMU","SDPC","SDRA",
    "SEMA","SFAN","SGER","SGGH","SGJL","SGRO","SHID","SHIP","SICO","SIDO",
    "SIER","SILO","SIMA","SIMP","SINI","SIPD","SKBM","SKLT","SKRN","SKYB",
    "SLIS","SMAR","SMDM","SMDR","SMGA","SMGR","SMKM","SMKL","SMLE","SMMA",
    "SMMT","SMRA","SMRU","SMSM","SNLK","SOCI","SOFA","SOHO","SOLA","SONA",
    "SOSS","SOTS","SOUL","SPMA","SPRE","SPTO","SQMI","SRAJ","SREI","SRIL",
    "SRSN","SRTG","SSIA","SSMS","SSTM","STAA","STAR","STRK","STTP","SUGI",
    "SULI","SUNI","SUPA","SUPR","SURE","SWAT","SWID","SYAI","TALF","TAMA",
    "TAMU","TAPG","TARA","TAXI","TAYS","TBIG","TBLA","TBMS","TCID","TCPI",
    "TDPM","TEBE","TECH","TELE","TFAS","TFCO","TGKA","TGRA","TGUK","TIFA",
    "TINS","TIRA","TIRT","TKIM","TLDN","TLKM","TMAS","TMPO","TNCA","TOBA",
    "TOOL","TOPS","TOSK","TOTL","TOTO","TOWR","TOYS","TPAI","TPIA","TPMA",
    "TRAM","TRGU","TRIL","TRIM","TRIN","TRIO","TRIS","TRJA","TRON","TRST",
    "TRUE","TRUK","TRUS","TSPC","TUGU","TULT","TYRE","UANG","UCID","UDNG",
    "UFOE","ULTJ","UNIC","UNIQ","UNIT","UNSP","UNTR","UNVR","URBN","UVCR",
    "VAST","VATE","VCOK","VERN","VICI","VICO","VINS","VISA","VISI","VIVA",
    "VKTR","VOKS","VOSS","VRNA","VTNY","WAPO","WBSA","WEGE","WEHA","WGSH",
    "WICO","WIDI","WIFI","WIIM","WIKA","WINE","WINR","WINS","WIRG","WITA",
    "WMPP","WMUU","WOMF","WONS","WOOD","WOWS","WPOW","WSBP","WSKT","WTON",
    "YELO","YOII","YPAS","YULE","YUPI","ZATA","ZBRA","ZENI","ZINC","ZONE",
    "ZYRX",
]

# ─── US TICKER UNIVERSE (583 stocks for multi-scan) ───────────────
US_TICKERS = [
    "AAPL","MSFT","GOOGL","GOOG","AMZN","NVDA","META","TSLA","AVGO","ORCL",
    "BRK-B","JPM","V","WMT","XOM","LLY","MA","JNJ","UNH","PG",
    "HD","CVX","ABBV","KO","MRK","COST","BAC","CRM","TMO","PEP",
    "WFC","ADBE","CSCO","ABT","ACN","NFLX","DIS","MCD","LIN","DHR",
    "TXN","NEE","VZ","CMCSA","RTX","PM","UPS","NKE","INTU","T",
    "AMD","QCOM","HON","LOW","PFE","COP","IBM","UNP","INTC","ELV",
    "SPGI","BMY","CAT","DE","GE","SBUX","BA","BLK","AMAT","BKNG",
    "GILD","AMGN","NOW","ISRG","SYK","LMT","MDT","ADI","PLD","TJX",
    "VRTX","AXP","C","SCHW","CB","REGN","ADP","MMC","ZTS","GS",
    "PYPL","MO","CI","SLB","BDX","FI","CL","SO","TGT","DUK",
    "TSM","ASML","MU","LRCX","KLAC","MRVL","NXPI","MCHP","ON","SWKS",
    "STM","WDC","STX","ENTG","AMKR","FORM","UCTT","ACLS","SIMO","HIMX",
    "SHOP","SQ","UBER","LYFT","ABNB","DASH","SNAP","PINS","TWTR","RBLX",
    "U","NET","DDOG","SNOW","CRWD","ZS","PANW","FTNT","OKTA","MDB",
    "TEAM","WDAY","HUBS","ZM","DOCU","TWLO","PATH","AI","SMCI","PLTR",
    "C3AI","SOUN","BBAI","UPST","ASAN","ESTC","CFLT","S","GTLB","RIVN",
    "LCID","NIO","XPEV","LI","CHPT","BLNK","QS","SLDP","FSR","WKHS",
    "NKLA","HYZN","PLUG","FCEL","BE","ALB","SQM","LAC","BABA","JD",
    "PDD","BIDU","NTES","BILI","TCEHY","TME","BEKE","TAL","EDU","IQ",
    "HUYA","DOYU","GDS","VIPS","YMM","MRNA","BNTX","BIIB","ILMN","ALNY",
    "SGEN","INCY","BMRN","EXEL","TECH","CRSP","NTLA","BEAM","EDIT","SANA",
    "BLUE","RPRX","JAZZ","CVS","HUM","ANTM","ALXN","NVAX","MS","ICE",
    "CME","BX","KKR","APO","CG","COIN","HOOD","SOFI","AFRM","MKTX",
    "NDAQ","TROW","STT","BK","FIS","FISV","GPN","WU","EOG","OXY",
    "PXD","MPC","VLO","PSX","HES","DVN","FANG","APA","CTRA","MRO",
    "KMI","WMB","ENB","ET","TPL","HAL","BKR","NOV","RIG","NE",
    "VAL","TS","NEX","WHD","TM","CMG","ORLY","AZO","ROST","LULU",
    "BURL","DPZ","YUM","DRI","GM","F","HOG","CARG","CVNA","KMX",
    "AN","KMB","GIS","K","HSY","STZ","TAP","SAM","DEO","BUD",
    "KDP","MNST","CHD","CLX","ENR","TMUS","CHTR","WBD","FOX","FOXA",
    "NWS","NWSA","PARA","SIRI","LSXMA","LSXMK","FDX","NOC","GD","TXT",
    "EMR","ETN","ITW","PH","CMI","ROK","DOV","FTV","XYL","AME",
    "WM","RSG","WCN","CSX","NSC","CHRW","JBHT","EXPD","ODFL","AMT",
    "CCI","EQIX","DLR","O","SPG","WELL","PSA","EXR","AVB","EQR",
    "ESS","INVH","SBAC","ARE","VTR","VICI","HST","REG","CEG","SRE",
    "AEP","D","PCG","EXC","XEL","PEG","ED","APD","SHW","FCX",
    "NEM","NUE","STLD","DOW","DD","ECL","PPG","GOLD","AEM","KGC",
    "AG","PAAS","HL","CDE","WPM","FNV","RGLD","X","CLF","MT",
    "RIO","BHP","VALE","SCCO","TECK","MSTR","MARA","RIOT","CLSK","HUT",
    "BITF","CIFR","CAN","BTBT","WULF","HIVE","DGHI","NCTY","BTCS","SOS",
    "EBON","CIPHER","GME","AMC","BB","NOK","WISH","CLOV","SPCE","TLRY",
    "CGC","CRON","ACB","HEXO","SNDL","CURLF","TCNNF","GTBIF","VFF","DWAC",
    "CFVI","PHUN","BBBY","ATER","BBIG","PROG","MULN","FFIE","HKD","HII",
    "KTOS","AVAV","LHX","TDG","HEI","ESLT","BWXT","CW","MRCY","LDOS",
    "SAIC","BAH","CACI","MAR","HLT","H","IHG","WH","CHH","RCL",
    "CCL","NCLH","UAL","DAL","AAL","LUV","ALK","JBLU","HA","SAVE",
    "ALGT","MGM","WYNN","LVS","CZR","DKNG","PENN","BYD","CHDN","RRR",
    "FLL","CYBR","TENB","RPD","FEYE","ENPH","SEDG","FSLR","RUN","NOVA",
    "SPWR","CSIQ","JKS","ARRY","SHLS","BLDP","HYG","BEPC","TAN","ICLN",
    "QCLN","ETSY","EBAY","W","CHWY","MELI","AFFIRM","ROKU","PLBY","SKLZ",
    "OPEN","Z","RDFN","WBA","KSS","M","JWN","GPS","BIG","DLTR",
    "FIVE","OLLI","ULTA","BBWI","TPR","CPRI","RL","LEVI","PVH","HBI",
    "UAA","CROX","ONON","SPY","QQQ","IWM","DIA","VTI","VOO","VEA",
    "VWO","BND","TLT","GLD","SLV","USO","UNG","DBC","DBA","XLE",
    "XLF","XLK","XLV","XLI","XLY","XLP","XLU","XLB","XLRE","XLC",
    "ARKK","ARKG","ARKW","ARKQ","ARKF","SOXX","SMH","IBB","XBI","KRE",
    "KBE","XOP","OIH","TQQQ","SQQQ","SOXL","SOXS","TNA","TZA","UPRO",
    "SPXS","UDOW","SDOW","VXX","UVXY","SVXY","SVOL","JEPI","JEPQ","SCHD",
    "DGRO","VYM","DVY",
]

# ─── CRYPTO TICKER UNIVERSE (208 coins for multi-scan) ────────────
CRYPTO_TICKERS = [
    # --- NEW CRYPTO ---
    "XAUT-USD", "PAXG-USD", "DEXE-USD", "APT-USD", "FARTCOIN-USD", "GOMINING-USD", "GLM-USD", "JELLYJELLY-USD", "DGB-USD",    
    "T-USD", "MASK-USD", "OSMO-USD", "SKL-USD", "LSK-USD", "AVA-USD", "ADX-USD", "COS-USD",
    
    # --- TERSEDIA DI PRO ---
    "TAO-USD", "INJ-USD", "PENDLE-USD", "W-USD",

    # --- MEME ---
    "SHIB-USD", "PEPE-USD", "BONK-USD", "FLOKI-USD", "WIF-USD", "ORDI-USD", "TURBO-USD", "PNUT-USD", "MEME-USD",
    "MEW-USD", "BOME-USD", "NEIRO-USD", "PEOPLE-USD", "CATI-USD", "DOGS-USD", "ACT-USD",

    # --- GAMING ---
    "BEAMX-USD", "NOT-USD", "RONIN-USD", "ILV-USD", "YGG-USD", "PIXEL-USD", "XAI-USD", "PORTAL-USD", "ALICE-USD", 
    "ACE-USD",

    # --- AI & BIG DATA ---
    "WLD-USD", "ATH-USD", "IO-USD", "IQ-USD", "AI-USD", "NFP-USD",

    # --- DEFI ---
    "ENA-USD", "CRV-USD", "ZRO-USD", "ETHFI-USD", "STG-USD", "CVX-USD", "RUNE-USD", "1INCH-USD", "DYDX-USD", 
    "RSR-USD", "YFI-USD", "NMR-USD", "GMX-USD", "SUSHI-USD", "AMP-USD", "UMA-USD", "BNT-USD", "REZ-USD",
    "BB-USD", "API3-USD", "LISTA-USD", "SPELL-USD", "C98-USD", "GNS-USD", "HFT-USD", "BEL-USD",

    # --- LAYER 1 ---
    "BTC-USD", "ETH-USD", "SOL-USD", "TON-USD", "HBAR-USD", "SUI-USD", "NEAR-USD", "DOT-USD", "ICP-USD", "INJ-USD",
    "SEI-USD", "CKB-USD", "MINA-USD", "AXL-USD", "ASTR-USD", "XNO-USD", "DUSK-USD", "VTHO-USD", "MANTA-USD", "LUNA-USD",
    "WAVES-USD", "STRAX-USD", "MOVR-USD", "GLMR-USD", "VIC-USD",

    # --- LAYER 2 ---
    "ARB-USD", "STRK-USD", "ZK-USD", "METIS-USD", "PROM-USD", "AEVO-USD", "ARPA-USD", "DYM-USD",

    # --- INFRASTRUKTUR ---
    "QNT-USD", "TIA-USD", "PYTH-USD", "TWT-USD", "AR-USD", "LPT-USD", "ZRX-USD", "ACH-USD",
    "ROSE-USD", "ALT-USD", "SC-USD", "SSV-USD", "TRB-USD", "IOTX-USD", "COTI-USD", "CYBER-USD",
    "CTK-USD", "BICO-USD", "RAD-USD",

    # --- NFT ---
    "CHZ-USD", "SUPER-USD", "BLUR-USD", "GMT-USD", "AGLD-USD", 

    # --- WEB3 ---
    "CFX-USD", "CVC-USD", "AUDIO-USD", "MBL-USD",

    # --- FAN TOKEN ---
    "OG-USD", "ATM-USD", "BAR-USD", "PORTO-USD", "LAZIO-USD", "CITY-USD", "ACM-USD",

    # --- STABLECOINS ---
    "USDT-USD", "USDC-USD", "USTC-USD", "USDP-USD",
]

# ─── MARKET CONFIGS for multi-scan (used by scan_market_*) ────────
MARKET_CONFIGS = {
    "IDX": {
        "tickers": IDX_TICKERS, "suffix": ".JK",
        "label": "IDX (Indonesia)", "flag": "🇮🇩", "name": "IDX",
        "currency_fn": lambda p: f"Rp {p:,.0f}",
    },
    "US": {
        "tickers": US_TICKERS, "suffix": "",
        "label": "US Stocks", "flag": "🇺🇸", "name": "US",
        "currency_fn": lambda p: f"${_pf(p)}",
    },
    "Crypto": {
        "tickers": CRYPTO_TICKERS, "suffix": "-USD",
        "label": "Crypto", "flag": "₿", "name": "Crypto",
        "currency_fn": lambda p: f"${_pf(p)}",
    },
}


def format_ticker(raw_ticker, market):
    """Auto-add suffix based on selected market. Idempotent."""
    t = raw_ticker.strip().upper()
    if not t: return ""
    # If user already typed full yFinance format (with suffix), keep it
    has_suffix = any(s in t for s in [".JK", "-USD", "=X", "=F", "^"])
    if has_suffix: return t

    # Smart suffix logic per market
    if market == "Commodity":
        # PRIORITY 1: Known alias map (XAUUSD→GC=F because yFinance spot data unreliable)
        if t in COMMODITY_ALIAS:
            return COMMODITY_ALIAS[t]
        # PRIORITY 2: 5+ letter ending in currency code = spot pair (try =X for less common pairs)
        currency_endings = ("USD","EUR","JPY","GBP","CHF","AUD","CAD","CNY","SGD","HKD")
        if len(t) >= 5 and t.endswith(currency_endings):
            return f"{t}=X"
        # PRIORITY 3: Exactly 2 letters alpha = futures code (GC, SI, CL, HG, NG, ES, NQ, etc.)
        if len(t) == 2 and t.isalpha():
            return f"{t}=F"
        # FALLBACK: 3+ letter codes = ETF or stock-like (GLD, IAU, USO, SLV, DBA) → no suffix
        return t

    suffix = MARKET_SUFFIX.get(market, "")
    return f"{t}{suffix}" if suffix else t

# ─── TIMEFRAME CONFIG — driven by trading style ────────────────────
# Each TF defines: data period, multi-horizon τ for features,
# forecast horizons (how far ahead to predict), and default T1 window.
TF_CONFIG = {
    "5m": {
        "label": "Scalping ⚡",
        "period": "60d",  # yFinance max for 5m
        "min_bars": 200,
        "tau_bars":   [3, 6, 12, 24, 48],          # 15m, 30m, 1h, 2h, 4h
        "tau_labels": ["15m", "30m", "1h", "2h", "4h"],
        "forecast_bars":   [1, 3, 12],              # 5m, 15m, 1h
        "forecast_labels": ["5M", "15M", "1H"],
        "default_T1": 96,                           # ~8 hours
    },
    "15m": {
        "label": "Intraday 📊",
        "period": "60d",
        "min_bars": 150,
        "tau_bars":   [2, 4, 12, 24, 48],          # 30m, 1h, 3h, 6h, 12h
        "tau_labels": ["30m", "1h", "3h", "6h", "12h"],
        "forecast_bars":   [1, 4, 16],              # 15m, 1h, 4h
        "forecast_labels": ["15M", "1H", "4H"],
        "default_T1": 120,                          # ~30 hours
    },
    "30m": {
        "label": "Intraday 📊",
        "period": "60d",
        "min_bars": 100,
        "tau_bars":   [2, 4, 8, 16, 32],           # 1h, 2h, 4h, 8h, 16h
        "tau_labels": ["1h", "2h", "4h", "8h", "16h"],
        "forecast_bars":   [1, 2, 8],               # 30m, 1h, 4h
        "forecast_labels": ["30M", "1H", "4H"],
        "default_T1": 96,                           # ~2 days
    },
    "1h": {
        "label": "Swing Entry 🎯",
        "period": "730d",
        "min_bars": 80,
        "tau_bars":   [2, 4, 8, 24, 48],           # 2h, 4h, 8h, 1d, 2d
        "tau_labels": ["2h", "4h", "8h", "1d", "2d"],
        "forecast_bars":   [1, 4, 24],              # 1h, 4h, 1d
        "forecast_labels": ["1H", "4H", "1D"],
        "default_T1": 120,                          # ~5 days
    },
    "1d": {
        "label": "Swing/Position 📈",
        "period": "10y",
        "min_bars": 80,
        "tau_bars":   [2, 5, 10, 20, 60],          # 2d, 1w, 2w, 1mo, 3mo
        "tau_labels": ["2d", "1w", "2w", "1mo", "3mo"],
        "forecast_bars":   [1, 5, 22],              # 1d, 1w, 1mo
        "forecast_labels": ["1D", "1W", "1MO"],
        "default_T1": 100,                          # ~5 months
    },
    "1wk": {
        "label": "Bagger 💎",
        "period": "10y",
        "min_bars": 50,
        "tau_bars":   [2, 4, 8, 13, 26],           # 2w, 1mo, 2mo, 3mo, 6mo
        "tau_labels": ["2w", "1mo", "2mo", "3mo", "6mo"],
        "forecast_bars":   [1, 4, 13],              # 1w, 1mo, 3mo
        "forecast_labels": ["1W", "1MO", "3MO"],
        "default_T1": 60,                           # ~1.3 years
    },
}

# ─── SMART PRICE FORMATTER ────────────────────────────────────────
def _curr(market):
    """Currency symbol: Rp for IDX (user trades in Rupiah), $ for everything else."""
    return "Rp" if market == "IDX (Indonesia)" else "$"

def _pf(price):
    """Smart number formatter (handles wide price range: $0.00001 to $100,000)."""
    try:
        p = float(price)
        if p <= 0: return "0"
        if p >= 10000:    return f"{p:,.0f}"
        elif p >= 100:    return f"{p:,.2f}"
        elif p >= 10:     return f"{p:.2f}"
        elif p >= 1:      return f"{p:.3f}"
        elif p >= 0.01:   return f"{p:.4f}"
        elif p >= 0.0001: return f"{p:.6f}"
        else:             return f"{p:.8f}"
    except: return "0"

def _pf_idx(price):
    """IDR formatter - integer with thousand separators (saham IDR jarang ada desimal)."""
    try:
        p = float(price)
        if p <= 0: return "0"
        return f"{p:,.0f}"
    except: return "0"

def _price(price, market):
    """Final formatter: 'Rp 8,975' for IDX, '$2,034.50' for others."""
    sym = _curr(market)
    if market == "IDX (Indonesia)":
        return f"{sym} {_pf_idx(price)}"
    return f"{sym}{_pf(price)}"

def _pct(v, dp=2):
    try: return f"{float(v):+.{dp}f}%"
    except: return "0.00%"

# ─── DATA FETCH (anti-rate-limit) ─────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlcv(ticker, period, interval):
    """3-layer fallback yFinance fetch."""
    try:
        time.sleep(random.uniform(0.05, 0.15))
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, actions=False)
            if df is not None and len(df) > 0:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        try:
            df = yf.download(ticker, period=period, interval=interval,
                            progress=False, threads=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
            if df is not None and len(df) > 0:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        return None
    except: return None

def fetch_primary(ticker, tf):
    """Fetch primary timeframe based on TF_CONFIG."""
    cfg = TF_CONFIG[tf]
    return fetch_ohlcv(ticker, cfg["period"], tf)

# ════════════════════════════════════════════════════════════════════
#  CORE ENGINE — Section 18.2 (ANN-style features)
# ════════════════════════════════════════════════════════════════════

def compute_normalized_returns(close, T1):
    """Z-score normalize returns: R̂(t,T1) = (R(t) - meanR_T1) / σ_T1"""
    R = close.pct_change()
    R_mean = R.rolling(T1, min_periods=max(5, T1//3)).mean()
    R_demeaned = R - R_mean
    sigma = R_demeaned.rolling(T1, min_periods=max(5, T1//3)).std()
    R_hat = (R_demeaned / sigma.replace(0, np.nan)).fillna(0)
    return R_hat, R_demeaned, sigma

def compute_ema_features(R_hat, tau):
    lam = (tau - 1) / (tau + 1)
    return R_hat.ewm(alpha=1-lam, adjust=False).mean()

def compute_emsd_features(R_hat, tau):
    lam = (tau - 1) / (tau + 1)
    ema = R_hat.ewm(alpha=1-lam, adjust=False).mean()
    var = ((R_hat - ema) ** 2).ewm(alpha=1-lam, adjust=False).mean()
    return np.sqrt(var)

def compute_rsi_normalized(R_hat, tau):
    pos = R_hat.where(R_hat > 0, 0)
    neg = (-R_hat).where(R_hat < 0, 0)
    sum_pos = pos.rolling(tau, min_periods=2).sum()
    sum_neg = neg.rolling(tau, min_periods=2).sum()
    total = sum_pos + sum_neg
    return (sum_pos / total.replace(0, np.nan)).fillna(0.5)

def build_feature_matrix(df, T1, tau_bars):
    """Build feature matrix with DYNAMIC τ list per timeframe config."""
    close = df["Close"]
    R_hat, R_dem, sigma = compute_normalized_returns(close, T1)
    features = pd.DataFrame(index=df.index)
    features["R_hat"] = R_hat
    for tau in tau_bars:
        features[f"ema_{tau}"]  = compute_ema_features(R_hat, tau)
        features[f"emsd_{tau}"] = compute_emsd_features(R_hat, tau)
        features[f"rsi_{tau}"]  = compute_rsi_normalized(R_hat, tau)
    features = features.dropna()
    return features, R_hat, sigma

# ════════════════════════════════════════════════════════════════════
#  KNN PATTERN MATCHER — Section 3.17
# ════════════════════════════════════════════════════════════════════

def knn_pattern_match(features, close, k=20, lookback_horizon=4):
    if len(features) < 30 or len(close) < 30:
        return 0.0, [], [], [], 0.0
    feature_cols = [c for c in features.columns if c.startswith(('ema_','rsi_'))]
    X = features[feature_cols].values
    close_aligned = close.reindex(features.index).ffill()
    future_close = close_aligned.shift(-lookback_horizon)
    Y = (future_close / close_aligned - 1).values
    valid = ~np.isnan(Y)
    if valid.sum() < k + 5:
        return 0.0, [], [], [], 0.0
    X_hist = X[valid][:-1]; Y_hist = Y[valid][:-1]; X_now = X[-1]
    if np.any(np.isnan(X_now)) or np.any(np.isinf(X_now)):
        return 0.0, [], [], [], 0.0
    X_mean = X_hist.mean(axis=0); X_std = X_hist.std(axis=0) + 1e-9
    X_hist_z = (X_hist - X_mean) / X_std
    X_now_z = (X_now - X_mean) / X_std
    distances = np.linalg.norm(X_hist_z - X_now_z, axis=1)
    k_actual = min(k, len(distances))
    k_idx = np.argpartition(distances, k_actual-1)[:k_actual]
    k_idx = k_idx[np.argsort(distances[k_idx])]
    k_dist = distances[k_idx]; k_outcomes = Y_hist[k_idx]
    weights = 1 / (k_dist + 1e-6); weights = weights / weights.sum()
    pred_return = float(np.dot(weights, k_outcomes))
    outcome_std = np.std(k_outcomes); global_std = np.std(Y_hist) + 1e-9
    confidence = max(0.0, min(1.0, 1.0 - outcome_std / global_std))
    valid_indices = features.index[valid][:-1]
    k_timestamps = valid_indices[k_idx].tolist()
    return pred_return, k_timestamps, k_dist.tolist(), k_outcomes.tolist(), confidence

# ════════════════════════════════════════════════════════════════════
#  CONFLUENCE AGGREGATOR — Section 3.20
# ════════════════════════════════════════════════════════════════════

def compute_confluence_score(features, tau_bars, tau_labels):
    """Sub-score per horizon with DYNAMIC labels."""
    if len(features) < 10:
        return {}
    # Weight schema: middle horizons get more weight (sweet spot)
    n = len(tau_bars)
    raw_weights = [0.10, 0.20, 0.25, 0.25, 0.20][:n]
    total = sum(raw_weights)
    horizon_weights = {tau: w/total for tau, w in zip(tau_bars, raw_weights)}
    horizon_labels_map = dict(zip(tau_bars, tau_labels))

    latest = features.iloc[-1]
    breakdown = {}
    for tau in tau_bars:
        ema_v  = float(latest.get(f"ema_{tau}", 0))
        emsd_v = float(latest.get(f"emsd_{tau}", 0.01))
        rsi_v  = float(latest.get(f"rsi_{tau}", 0.5))

        trend_score = np.tanh(ema_v * 2) * 100
        momentum_score = min(100, max(-100, ema_v / max(emsd_v, 1e-6) * 50))
        rsi_centered = (rsi_v - 0.5) * 2
        rsi_score = rsi_centered * 60 if abs(rsi_centered) < 0.5 else -rsi_centered * 40
        sub_score = trend_score * 0.5 + momentum_score * 0.3 + rsi_score * 0.2

        breakdown[tau] = {
            "label": horizon_labels_map[tau],
            "weight": horizon_weights[tau],
            "trend": trend_score, "momentum": momentum_score,
            "rsi_raw": rsi_v, "rsi_score": rsi_score,
            "sub_score": sub_score,
            "ema_raw": ema_v, "emsd_raw": emsd_v,
        }
    return breakdown

def aggregate_confluence(breakdown):
    if not breakdown:
        return 0.0, 0.0
    weighted_sum = sum(b["sub_score"] * b["weight"] for b in breakdown.values())
    signs = [np.sign(b["sub_score"]) for b in breakdown.values()]
    agreement = abs(sum(signs)) / len(signs) if signs else 0.0
    confidence = min(1.0, 0.4 + 0.6 * agreement)
    return float(weighted_sum), float(confidence)

# ════════════════════════════════════════════════════════════════════
#  PROBABILITY MAPPING
# ════════════════════════════════════════════════════════════════════

def score_to_probability(composite_score, confidence, knn_pred, knn_conf, scale=35):
    score_prob = 1 / (1 + np.exp(-composite_score / scale))
    knn_score = knn_pred * 5000
    knn_prob = 1 / (1 + np.exp(-knn_score))
    total_weight = confidence + knn_conf + 1e-9
    raw_prob = (score_prob * confidence + knn_prob * knn_conf) / total_weight
    overall_conf = (confidence + knn_conf) / 2
    final_prob = 0.5 + (raw_prob - 0.5) * overall_conf
    return float(final_prob), float(overall_conf)

# ════════════════════════════════════════════════════════════════════
#  ATR-BASED ENTRY/TP/SL
# ════════════════════════════════════════════════════════════════════

def compute_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr

def compute_entry_levels(df, direction, prob, atr_mult_sl=1.0):
    if len(df) < 20:
        return None
    price = float(df["Close"].iloc[-1])
    atr = compute_atr(df, 14).iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None
    adapt_tp = 1.5 + (prob - 0.5) * 2
    adapt_tp = max(1.0, min(3.5, adapt_tp))
    if direction == "LONG":
        entry = price; tp1 = price + atr * 1.0; tp2 = price + atr * adapt_tp
        sl = price - atr * atr_mult_sl
        rr1 = (tp1 - entry) / (entry - sl) if entry > sl else 0
        rr2 = (tp2 - entry) / (entry - sl) if entry > sl else 0
    elif direction == "SHORT":
        entry = price; tp1 = price - atr * 1.0; tp2 = price - atr * adapt_tp
        sl = price + atr * atr_mult_sl
        rr1 = (entry - tp1) / (sl - entry) if sl > entry else 0
        rr2 = (entry - tp2) / (sl - entry) if sl > entry else 0
    else:
        return None
    return {"direction": direction, "entry": entry, "tp1": tp1, "tp2": tp2,
            "sl": sl, "atr": atr, "rr1": rr1, "rr2": rr2}

# ═══ REGIME DETECTORS ════════════════════════════════════════════════
def detect_volatility_regime(df):
    if len(df) < 50:
        return "UNKNOWN", "#4a5568"
    returns = df["Close"].pct_change()
    current_vol = returns.iloc[-20:].std()
    longterm_vol = returns.iloc[-200:].std() if len(returns) >= 200 else returns.std()
    if longterm_vol <= 0:
        return "UNKNOWN", "#4a5568"
    ratio = current_vol / longterm_vol
    if ratio < 0.7:   return "LOW",     "#4da6ff"
    if ratio < 1.3:   return "NORMAL",  "#00ff88"
    if ratio < 2.0:   return "HIGH",    "#ffb700"
    return "EXTREME", "#ff3d5a"

def detect_trend_regime(df):
    if len(df) < 50:
        return "UNKNOWN", "#4a5568"
    close = df["Close"]
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    price = close.iloc[-1]
    if price > ema20 > ema50: return "BULL TREND", "#00ff88"
    if price < ema20 < ema50: return "BEAR TREND", "#ff3d5a"
    if price > ema50 and price > ema20: return "BULL PULLBACK", "#4da6ff"
    if price < ema50 and price < ema20: return "BEAR PULLBACK", "#ff7b00"
    return "SIDEWAYS", "#ffb700"

# ════════════════════════════════════════════════════════════════════
#  MAIN ANALYZER (driven by TF_CONFIG)
# ════════════════════════════════════════════════════════════════════

def analyze_ticker(ticker, primary_tf="15m", T1=None, k=20, market="IDX (Indonesia)"):
    """Full analysis pipeline driven by TF_CONFIG."""
    cfg = TF_CONFIG[primary_tf]
    if T1 is None:
        T1 = cfg["default_T1"]

    df_main = fetch_primary(ticker, primary_tf)
    if df_main is None or len(df_main) < cfg["min_bars"] // 3:
        bars_count = len(df_main) if df_main is not None else 0
        return {"error": f"Data {primary_tf} kurang ({bars_count} bars). Butuh ≥{cfg['min_bars']//3} bars. Coba ticker lain atau timeframe lebih besar."}

    # Auto-adjust T1 jika data terbatas
    auto_T1 = min(T1, max(20, len(df_main) // 4))
    T1_used = auto_T1
    t1_note = f" (auto-adjusted from {T1})" if auto_T1 < T1 else ""

    features, R_hat, sigma = build_feature_matrix(df_main, T1_used, cfg["tau_bars"])
    if len(features) < 30:
        return {"error": f"Feature matrix terlalu pendek ({len(features)} valid bars). Coba timeframe lebih besar."}

    breakdown = compute_confluence_score(features, cfg["tau_bars"], cfg["tau_labels"])
    composite_score, score_conf = aggregate_confluence(breakdown)

    # Auto-adjust k
    k_used = min(k, max(5, len(features) // 4))

    # KNN for each forecast horizon defined in config
    forecasts = []
    for h_bars, h_label in zip(cfg["forecast_bars"], cfg["forecast_labels"]):
        # Wider sigmoid scale for longer horizons (more uncertainty)
        scale = 35 + (h_bars ** 0.5) * 5
        pred, knn_idx, knn_dist, knn_out, knn_conf = \
            knn_pattern_match(features, df_main["Close"], k=k_used, lookback_horizon=h_bars)
        prob, total_conf = score_to_probability(composite_score, score_conf, pred, knn_conf, scale=scale)

        if prob >= 0.60:    direction = "LONG"
        elif prob <= 0.40:  direction = "SHORT"
        else:                direction = "WAIT"

        wins = sum(1 for o in knn_out if o > 0)
        winrate = wins / len(knn_out) if knn_out else 0.5

        forecasts.append({
            "h_bars": h_bars, "label": h_label,
            "prob": prob, "conf": total_conf, "direction": direction,
            "knn_pred": pred, "knn_conf": knn_conf,
            "knn_idx": knn_idx, "knn_dist": knn_dist, "knn_out": knn_out,
            "winrate": winrate,
        })

    # Primary direction = first forecast (shortest horizon)
    primary_fc = forecasts[0]
    entry_levels = compute_entry_levels(df_main, primary_fc["direction"], primary_fc["prob"])

    vol_regime, vol_color = detect_volatility_regime(df_main)
    trend_regime, trend_color = detect_trend_regime(df_main)

    price = float(df_main["Close"].iloc[-1])
    prev_price = float(df_main["Close"].iloc[-2]) if len(df_main) > 1 else price
    change_pct = (price / prev_price - 1) * 100

    return {
        "ticker": ticker, "primary_tf": primary_tf, "tf_label": cfg["label"],
        "market": market,
        "price": price, "change_pct": change_pct,
        "atr": float(compute_atr(df_main, 14).iloc[-1]) if len(df_main) >= 15 else 0,
        "vol_regime": vol_regime, "vol_color": vol_color,
        "trend_regime": trend_regime, "trend_color": trend_color,
        "breakdown": breakdown,
        "composite_score": composite_score, "score_conf": score_conf,
        "forecasts": forecasts,
        "entry_levels": entry_levels,
        "df_main": df_main, "n_bars": len(df_main), "n_features": len(features),
        "T1_used": T1_used, "k_used": k_used, "t1_note": t1_note,
    }

# ════════════════════════════════════════════════════════════════════
#  TELEGRAM ALERTS
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
#  IDX MULTI-SCAN ENGINE — parallel fetch + primary-horizon prob
# ════════════════════════════════════════════════════════════════════

def _idx_analyze_one(df, T1, tau_bars, tau_labels, h_bars, h_label, k_req, scale):
    """Process a single fetched DataFrame through the engine. Returns dict or None."""
    if df is None or len(df) < 40:
        return None
    auto_T1 = min(T1, max(20, len(df) // 4))
    try:
        features, R_hat, sigma = build_feature_matrix(df, auto_T1, tau_bars)
        if len(features) < 30:
            return None
        breakdown = compute_confluence_score(features, tau_bars, tau_labels)
        composite_score, score_conf = aggregate_confluence(breakdown)
        k_used = min(k_req, max(5, len(features) // 4))
        pred, _idx, _dist, knn_out, knn_conf = knn_pattern_match(
            features, df["Close"], k=k_used, lookback_horizon=h_bars)
        prob, total_conf = score_to_probability(
            composite_score, score_conf, pred, knn_conf, scale=scale)

        if prob >= 0.60:   direction = "LONG"
        elif prob <= 0.40: direction = "SHORT"
        else:               direction = "WAIT"

        wins = sum(1 for o in knn_out if o > 0)
        winrate = wins / len(knn_out) if knn_out else 0.5

        entry_levels = compute_entry_levels(df, direction, prob)
        trend_regime, _ = detect_trend_regime(df)
        vol_regime, _ = detect_volatility_regime(df)

        price = float(df["Close"].iloc[-1])
        prev_price = float(df["Close"].iloc[-2]) if len(df) > 1 else price
        chg = (price/prev_price - 1) * 100

        return {
            "price": price, "change_pct": chg,
            "prob": prob, "conf": total_conf,
            "direction": direction, "winrate": winrate,
            "knn_pred": pred, "composite": composite_score,
            "trend": trend_regime, "vol": vol_regime,
            "entry": entry_levels, "n_bars": len(df),
            "label": h_label,
        }
    except Exception:
        return None

def scan_market_universe(market_key="IDX", timeframe="15m", T1=None, k=20, min_prob=0.55,
                          direction_filter="ALL", workers=6, progress_cb=None):
    """
    Generic universe scanner — works for IDX/US/Crypto.
    market_key picks ticker list, suffix, and currency from MARKET_CONFIGS.
    Returns (results_list, skip_reasons_dict).
    """
    mcfg = MARKET_CONFIGS[market_key]
    cfg = TF_CONFIG[timeframe]
    if T1 is None: T1 = cfg["default_T1"]

    suffix = mcfg["suffix"]
    tickers_yf = [t if (not suffix or t.endswith(suffix)) else f"{t}{suffix}" for t in mcfg["tickers"]]
    random.shuffle(tickers_yf)  # avoid pattern detection by yFinance
    n_total = len(tickers_yf)

    h_bars  = cfg["forecast_bars"][0]
    h_label = cfg["forecast_labels"][0]
    scale = 35 + (h_bars ** 0.5) * 5

    skip = {"no_data": 0, "features_fail": 0, "low_prob": 0, "wrong_dir": 0}
    results = []

    # Parallel fetch with humanized delays
    data_dict = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_ohlcv, t, cfg["period"], timeframe): t for t in tickers_yf}
        for i, f in enumerate(as_completed(futures)):
            t = futures[f]
            try: data_dict[t] = f.result()
            except: data_dict[t] = None
            if progress_cb and i % 10 == 0:
                progress_cb(i+1, n_total, "fetching")

    # Process each ticker
    for i, t_yf in enumerate(tickers_yf):
        df = data_dict.get(t_yf)
        if progress_cb and i % 20 == 0:
            progress_cb(i+1, n_total, "analyzing")

        if df is None or len(df) < cfg["min_bars"] // 3:
            skip["no_data"] += 1; continue

        result = _idx_analyze_one(df, T1, cfg["tau_bars"], cfg["tau_labels"],
                                   h_bars, h_label, k, scale)
        if result is None:
            skip["features_fail"] += 1; continue

        # Apply filters
        if direction_filter != "ALL" and result["direction"] != direction_filter:
            skip["wrong_dir"] += 1; continue

        # Probability filter — distance from 0.5
        prob_strength = abs(result["prob"] - 0.5) + 0.5
        if prob_strength < min_prob:
            skip["low_prob"] += 1; continue

        # Display ticker: strip suffix if any
        display = t_yf.replace(suffix, "") if suffix else t_yf
        result["ticker"] = display
        result["ticker_yf"] = t_yf
        result["market_key"] = market_key
        results.append(result)

    # Sort by absolute distance from 0.5 (strongest signals first)
    results.sort(key=lambda r: abs(r["prob"] - 0.5), reverse=True)
    return results, skip

# Backward-compat wrapper
def scan_idx_universe(timeframe="15m", T1=None, k=20, min_prob=0.55,
                       direction_filter="ALL", workers=6, progress_cb=None):
    return scan_market_universe("IDX", timeframe, T1, k, min_prob,
                                 direction_filter, workers, progress_cb)

# ════════════════════════════════════════════════════════════════════
#  MULTI-TF DECISION ENGINE — Combine 1H + 15m + 5m into single signal
# ════════════════════════════════════════════════════════════════════
# Philosophy:
#   • 1H  = BIAS direction (longer horizon, less noise) — 45% weight
#   • 15m = TRIGGER timing (entry decision)              — 35% weight
#   • 5m  = EXECUTION fine-tune (current momentum)       — 20% weight
# Decision Stars:
#   ★★★★ STRONG = all 3 TFs aligned + score ≥65 + agreement 100%
#   ★★★ VALID   = ≥2 TFs aligned + score ≥50 + agreement ≥66%
#   ★★ MONITOR  = partial alignment + score ≥35
#   ★ WEAK      = marginal signal, just watch
#   ✗ WAIT      = no clear setup

MULTI_TF_CONFIG = {
    "tfs": ["1h", "15m", "5m"],
    "weights": {"1h": 0.45, "15m": 0.35, "5m": 0.20},
    "roles":   {"1h": "BIAS", "15m": "TRIGGER", "5m": "EXECUTION"},
}

def _analyze_one_tf(df, tf_name, k_req=20):
    """Run full engine on a single TF's data. Returns dict or None."""
    if df is None or len(df) < 40:
        return None
    cfg = TF_CONFIG[tf_name]
    auto_T1 = min(cfg["default_T1"], max(20, len(df) // 4))
    try:
        features, _, _ = build_feature_matrix(df, auto_T1, cfg["tau_bars"])
        if len(features) < 30:
            return None
        breakdown = compute_confluence_score(features, cfg["tau_bars"], cfg["tau_labels"])
        composite, score_conf = aggregate_confluence(breakdown)
        h_bars = cfg["forecast_bars"][0]
        scale = 35 + (h_bars ** 0.5) * 5
        k_used = min(k_req, max(5, len(features) // 4))
        pred, _, _, knn_out, knn_conf = knn_pattern_match(
            features, df["Close"], k=k_used, lookback_horizon=h_bars)
        prob, conf = score_to_probability(composite, score_conf, pred, knn_conf, scale=scale)
        direction = "LONG" if prob >= 0.60 else "SHORT" if prob <= 0.40 else "WAIT"
        wins = sum(1 for o in knn_out if o > 0)
        winrate = wins / len(knn_out) if knn_out else 0.5
        return {
            "tf": tf_name, "prob": prob, "conf": conf,
            "direction": direction, "composite": composite,
            "winrate": winrate, "n_bars": len(df),
            "price": float(df["Close"].iloc[-1]),
        }
    except Exception:
        return None

def compute_multi_tf_score(tf_results):
    """Aggregate per-TF probabilities → Multi-TF Decision Score (0-100, stars 0-4).
    
    REVISED formula (v1.2.1): additive bonus instead of multiplicative penalty.
    Old formula penalized even fully-aligned mild signals (kept under threshold).
    New: agreement & confidence give explicit bonus points → more signals get rated.
    """
    valid_tfs = [tf for tf in MULTI_TF_CONFIG["tfs"] if tf_results.get(tf) is not None]
    if not valid_tfs:
        return {"score": 0, "stars": 0, "direction": "NO DATA",
                "agreement": 0, "label": "NO DATA", "color": "#4a5568",
                "avg_conf": 0, "tfs_analyzed": []}

    w = MULTI_TF_CONFIG["weights"]
    total_w = sum(w[tf] for tf in valid_tfs)

    # Weighted directional signal (-1 to +1, range usually -0.5 to +0.5)
    avg_signal = sum((tf_results[tf]["prob"] - 0.5) * 2 * w[tf]
                     for tf in valid_tfs) / total_w
    avg_conf = sum(tf_results[tf]["conf"] * w[tf]
                    for tf in valid_tfs) / total_w

    # Agreement: how many TFs same sign?
    signs = [np.sign(tf_results[tf]["prob"] - 0.5) for tf in valid_tfs]
    agreement = abs(sum(signs)) / len(signs) if signs else 0

    # ── NEW SCORING (additive) ──
    strength = abs(avg_signal)
    raw_score = strength * 100         # 0-100 (signal magnitude)
    bonus_agreement = agreement * 30   # max +30 untuk full alignment
    bonus_conf = avg_conf * 20         # max +20 untuk high confidence
    baseline_offset = 10               # subtract to avoid inflating pure noise
    adj_score = max(0, min(100, raw_score + bonus_agreement + bonus_conf - baseline_offset))

    # More permissive direction threshold (0.10 → 0.04)
    if avg_signal > 0.04:    direction = "LONG"
    elif avg_signal < -0.04: direction = "SHORT"
    else:                     direction = "WAIT"

    # Stars rating (recalibrated for new score range)
    if direction == "WAIT":
        stars, label, color = 0, "WAIT", "#ffb700"
    elif adj_score >= 65 and agreement >= 0.99:
        stars, label = 4, "STRONG ENTRY"
        color = "#00ff88" if direction == "LONG" else "#ff3d5a"
    elif adj_score >= 50 and agreement >= 0.66:
        stars, label = 3, "VALID ENTRY"
        color = "#00ff88" if direction == "LONG" else "#ff3d5a"
    elif adj_score >= 35 and agreement >= 0.33:
        stars, label, color = 2, "MONITOR", "#4da6ff"
    elif adj_score >= 15:
        stars, label, color = 1, "WEAK", "#ffb700"
    else:
        stars, label, color = 0, "WAIT", "#ffb700"

    return {
        "score": adj_score, "stars": stars, "direction": direction,
        "agreement": agreement, "avg_signal": avg_signal, "avg_conf": avg_conf,
        "label": label, "color": color,
        "tfs_analyzed": valid_tfs,
    }

def analyze_multi_tf(ticker, k=20, market="IDX (Indonesia)"):
    """
    Run engine on 1H + 15m + 5m simultaneously. Combine into Multi-TF Decision.
    Returns: per-TF results + combined score + entry levels + regime.
    """
    tfs = MULTI_TF_CONFIG["tfs"]
    # Parallel fetch all 3 TFs
    data = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fetch_primary, ticker, tf): tf for tf in tfs}
        for f in as_completed(futures):
            tf = futures[f]
            try: data[tf] = f.result()
            except: data[tf] = None

    # Analyze each TF
    tf_results = {}
    for tf in tfs:
        tf_results[tf] = _analyze_one_tf(data.get(tf), tf, k_req=k)

    # Combine
    score = compute_multi_tf_score(tf_results)

    # Entry levels: use 15m if available (intraday standard), else fallback
    # FIX: can't use `or` chain on DataFrames (ambiguous truth value crash)
    primary_df = None
    for _tf in ("15m", "1h", "5m"):
        _df = data.get(_tf)
        if _df is not None and len(_df) > 0:
            primary_df = _df; break
    if primary_df is None:
        return {"error": f"Tidak ada data fetchable untuk {ticker} di TF apapun"}

    # Use 15m probability for entry sizing; direction from multi-TF score
    p15_prob = tf_results.get("15m", {}).get("prob", 0.5) if tf_results.get("15m") else 0.5
    entry = compute_entry_levels(primary_df, score["direction"], p15_prob) if score["direction"] != "WAIT" else None

    # Regime: prefer 1H view (most stable). FIX: explicit None check, no DataFrame `or`.
    regime_df = None
    for _tf in ("1h", "15m", "5m"):
        _df = data.get(_tf)
        if _df is not None and len(_df) > 0:
            regime_df = _df; break
    if regime_df is not None:
        trend_regime, trend_color = detect_trend_regime(regime_df)
        vol_regime, vol_color = detect_volatility_regime(regime_df)
    else:
        trend_regime, trend_color = "UNKNOWN", "#4a5568"
        vol_regime, vol_color = "UNKNOWN", "#4a5568"

    price = float(primary_df["Close"].iloc[-1])
    prev = float(primary_df["Close"].iloc[-2]) if len(primary_df) > 1 else price
    change_pct = (price/prev - 1) * 100

    return {
        "ticker": ticker, "market": market,
        "tf_results": tf_results,
        "multi_tf": score,
        "entry": entry,
        "trend_regime": trend_regime, "trend_color": trend_color,
        "vol_regime": vol_regime, "vol_color": vol_color,
        "price": price, "change_pct": change_pct,
        "atr": float(compute_atr(primary_df, 14).iloc[-1]) if len(primary_df) >= 15 else 0,
    }

def scan_market_multi_tf(market_key="IDX", stage1_min_prob=0.52, top_n_stage2=100, k=20,
                          min_stars=1, direction_filter="ALL", workers=6, progress_cb=None):
    """
    Multi-TF scanner for any market (IDX/US/Crypto).
    • FULL UNIVERSE (top_n_stage2 >= total): bypass Stage 1, multi-TF analyze all
    • 2-STAGE: fast 15m pre-screen → multi-TF deep dive on top N
    """
    mcfg = MARKET_CONFIGS[market_key]
    suffix = mcfg["suffix"]
    n_total = len(mcfg["tickers"])
    full_universe_mode = top_n_stage2 >= n_total

    if full_universe_mode:
        # FULL UNIVERSE MODE — bypass Stage 1
        if progress_cb: progress_cb(0, n_total, "fullscan_init")
        tickers_yf = [t if (not suffix or t.endswith(suffix)) else f"{t}{suffix}" for t in mcfg["tickers"]]
        random.shuffle(tickers_yf)

        final_results = []
        stage2_skip = {"no_multi_data": 0, "below_stars": 0, "wrong_dir": 0}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(analyze_multi_tf, t, k=k, market=mcfg["label"]): t for t in tickers_yf}
            for i, f in enumerate(as_completed(futures)):
                t = futures[f]
                if progress_cb and i % 3 == 0:
                    progress_cb(i+1, n_total, "fullscan_multi_tf")
                try: mtf = f.result()
                except Exception:
                    stage2_skip["no_multi_data"] += 1; continue
                if mtf is None or mtf.get("error"):
                    stage2_skip["no_multi_data"] += 1; continue

                mscore = mtf["multi_tf"]
                if mscore["stars"] < min_stars:
                    stage2_skip["below_stars"] += 1; continue
                if direction_filter != "ALL" and mscore["direction"] != direction_filter:
                    stage2_skip["wrong_dir"] += 1; continue

                display = t.replace(suffix, "") if suffix else t
                final_results.append({
                    "ticker": display, "ticker_yf": t,
                    "price": mtf["price"], "change_pct": mtf["change_pct"],
                    "atr": mtf["atr"], "multi_tf": mscore,
                    "tf_results": mtf["tf_results"], "entry": mtf["entry"],
                    "trend": mtf["trend_regime"], "vol": mtf["vol_regime"],
                    "market_key": market_key,
                })

        final_results.sort(key=lambda r: r["multi_tf"]["score"], reverse=True)
        return final_results, {
            "mode": "full_universe", "market_key": market_key,
            "stage1_total": n_total, "stage1_passed": n_total,
            "stage1_skip": {}, "stage2_candidates": n_total,
            "stage2_passed": len(final_results), "stage2_skip": stage2_skip,
        }

    # 2-STAGE MODE
    if progress_cb: progress_cb(0, n_total, "stage1_init")
    stage1, stage1_skip = scan_market_universe(
        market_key=market_key, timeframe="15m", k=k, min_prob=stage1_min_prob,
        direction_filter="ALL", workers=workers,
        progress_cb=(lambda d, t, p: progress_cb(d, t, f"stage1_{p}")) if progress_cb else None
    )

    candidates = stage1[:top_n_stage2]
    n_cands = len(candidates)
    if not candidates:
        return [], {"mode": "2_stage", "market_key": market_key,
                    "stage1_total": n_total, "stage1_passed": 0, "stage2_passed": 0,
                    "stage1_skip": stage1_skip}

    final_results = []
    stage2_skip = {"no_multi_data": 0, "below_stars": 0, "wrong_dir": 0}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(analyze_multi_tf, c["ticker_yf"], k=k, market=mcfg["label"]): c for c in candidates}
        for i, f in enumerate(as_completed(futures)):
            c = futures[f]
            if progress_cb and i % 3 == 0:
                progress_cb(i+1, n_cands, "stage2_multi_tf")
            try: mtf = f.result()
            except Exception:
                stage2_skip["no_multi_data"] += 1; continue
            if mtf is None or mtf.get("error"):
                stage2_skip["no_multi_data"] += 1; continue

            mscore = mtf["multi_tf"]
            if mscore["stars"] < min_stars:
                stage2_skip["below_stars"] += 1; continue
            if direction_filter != "ALL" and mscore["direction"] != direction_filter:
                stage2_skip["wrong_dir"] += 1; continue

            final_results.append({
                "ticker": c["ticker"], "ticker_yf": c["ticker_yf"],
                "price": mtf["price"], "change_pct": mtf["change_pct"],
                "atr": mtf["atr"], "multi_tf": mscore,
                "tf_results": mtf["tf_results"], "entry": mtf["entry"],
                "trend": mtf["trend_regime"], "vol": mtf["vol_regime"],
                "market_key": market_key,
            })

    final_results.sort(key=lambda r: r["multi_tf"]["score"], reverse=True)
    return final_results, {
        "mode": "2_stage", "market_key": market_key,
        "stage1_total": n_total, "stage1_passed": len(stage1),
        "stage1_skip": stage1_skip, "stage2_candidates": n_cands,
        "stage2_passed": len(final_results), "stage2_skip": stage2_skip,
    }

# Backward-compat wrapper
def scan_idx_multi_tf(stage1_min_prob=0.52, top_n_stage2=100, k=20,
                       min_stars=1, direction_filter="ALL", workers=6, progress_cb=None):
    return scan_market_multi_tf("IDX", stage1_min_prob, top_n_stage2, k,
                                 min_stars, direction_filter, workers, progress_cb)

def send_telegram_multi_tf_batch(top_results, market_key="IDX"):
    """Send top multi-TF results to Telegram (market-aware: IDX/US/Crypto)."""
    if not TOKEN or not CHAT_ID:
        return False, "Telegram tidak dikonfigurasi"
    if not top_results:
        return False, "Tidak ada signal"
    mcfg = MARKET_CONFIGS.get(market_key, MARKET_CONFIGS["IDX"])
    cur_fn = mcfg["currency_fn"]
    now = datetime.now(et_tz); sep = "━" * 28
    body = (
        f"{mcfg['flag']} *MESIN ENTRY MULTI-TF SCAN — {mcfg['name'].upper()}*\n"
        f"{sep}\n"
        f"📊 Engine: 1H + 15m + 5m confluence\n"
        f"⏰ `{now.strftime('%H:%M:%S')} ET` · `{now.strftime('%d %b %Y')}`\n"
        f"🎯 Top {len(top_results)} signals by multi-TF score:\n"
        f"{sep}\n"
    )
    for i, r in enumerate(top_results, 1):
        m = r["multi_tf"]
        tfs = r["tf_results"]
        stars = "★" * m["stars"] + "☆" * (4 - m["stars"])
        dir_emoji = "🟢" if m["direction"]=="LONG" else "🔴" if m["direction"]=="SHORT" else "⚪"

        tf_summary = ""
        for tf_name in ["1h", "15m", "5m"]:
            tr = tfs.get(tf_name)
            if tr:
                tf_dir = "🟢" if tr["direction"]=="LONG" else "🔴" if tr["direction"]=="SHORT" else "⚪"
                tf_summary += f"   {tf_name:>3}: {tf_dir} {tr['prob']*100:.0f}% · "
            else:
                tf_summary += f"   {tf_name:>3}: ✗ no data · "
        tf_summary = tf_summary.rstrip(" ·") + "\n"

        body += (
            f"\n{i}. {stars} {dir_emoji} *{r['ticker']}* @ `{cur_fn(r['price'])}` ({_pct(r['change_pct'])})\n"
            f"   *{m['label']}* · Score: `{m['score']:.0f}/100` · Conf `{m['avg_conf']*100:.0f}%`\n"
            f"{tf_summary}"
            f"   Regime: {r['trend']} · Vol: {r['vol']}\n"
        )
        if r["entry"]:
            e = r["entry"]
            body += f"   💰 Entry `{cur_fn(e['entry'])}` · TP `{cur_fn(e['tp1'])}` · SL `{cur_fn(e['sl'])}` · R:R `{e['rr1']:.1f}`\n"
    body += (
        f"\n{sep}\n"
        f"⚡ _Mesin Entry Multi-TF v1.3_\n"
        f"⚠️ _Probabilistik, BUKAN guarantee. Pakai R:R + position sizing!_"
    )
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": body, "parse_mode": "Markdown"},
            timeout=15
        )
        if r.status_code == 200: return True, "Terkirim ✅"
        return False, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"

def send_telegram_idx_batch(top_results, timeframe, market_key="IDX"):
    """Send top single-TF results to Telegram (market-aware)."""
    if not TOKEN or not CHAT_ID:
        return False, "Telegram tidak dikonfigurasi"
    if not top_results:
        return False, "Tidak ada signal untuk dikirim"
    mcfg = MARKET_CONFIGS.get(market_key, MARKET_CONFIGS["IDX"])
    cur_fn = mcfg["currency_fn"]
    now = datetime.now(et_tz); sep = "━" * 28
    body = (
        f"{mcfg['flag']} *MESIN ENTRY {mcfg['name'].upper()} SCAN*\n"
        f"{sep}\n"
        f"📊 Timeframe: *{timeframe}* · {TF_CONFIG[timeframe]['label']}\n"
        f"⏰ `{now.strftime('%H:%M:%S')} ET` · `{now.strftime('%d %b %Y')}`\n"
        f"🎯 Top {len(top_results)} signals by probability:\n"
        f"{sep}\n"
    )
    for i, r in enumerate(top_results, 1):
        dir_emoji = "🟢" if r["direction"]=="LONG" else "🔴" if r["direction"]=="SHORT" else "⚪"
        body += (
            f"\n{i}. {dir_emoji} *{r['ticker']}* @ `{cur_fn(r['price'])}` ({_pct(r['change_pct'])})\n"
            f"   P({r['label']}): `{r['prob']*100:.1f}%` · Conf `{r['conf']*100:.0f}%` · Win `{r['winrate']*100:.0f}%`\n"
            f"   Regime: {r['trend']} · Vol: {r['vol']}\n"
        )
        if r["entry"]:
            e = r["entry"]
            body += f"   Entry `{cur_fn(e['entry'])}` · TP `{cur_fn(e['tp1'])}` · SL `{cur_fn(e['sl'])}`\n"
    body += (
        f"\n{sep}\n"
        f"⚡ _Mesin Entry {mcfg['name']} Scan v1.3_\n"
        f"⚠️ _Probabilistik, BUKAN guarantee!_"
    )
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": body, "parse_mode": "Markdown"},
            timeout=10
        )
        if r.status_code == 200: return True, "Terkirim ✅"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"

def send_telegram(ticker, result):
    if not TOKEN or not CHAT_ID:
        return False, "Telegram tidak dikonfigurasi (set secrets)"
    now = datetime.now(et_tz); sep = "━" * 28

    primary = result["forecasts"][0]
    secondary = result["forecasts"][1] if len(result["forecasts"]) > 1 else None
    dir_emoji = "🟢 LONG" if primary["direction"] == "LONG" else "🔴 SHORT" if primary["direction"] == "SHORT" else "⚪ WAIT"

    body = (
        f"🎯 *MESIN ENTRY ALERT*\n"
        f"{sep}\n"
        f"📊 *{ticker}* @ `{_price(result['price'], result['market'])}` ({_pct(result['change_pct'])})\n"
        f"🎚 TF: *{result['primary_tf']}* — {result['tf_label']}\n"
        f"⏰ `{now.strftime('%H:%M:%S')} ET` · `{now.strftime('%d %b %Y')}`\n"
        f"{sep}\n"
        f"🎯 *{primary['label']} FORECAST*\n"
        f"   {dir_emoji} · Probability: `{primary['prob']*100:.1f}%`\n"
        f"   Confidence: `{primary['conf']*100:.0f}%`\n"
        f"   KNN Win Rate: `{primary['winrate']*100:.0f}%`\n"
    )
    if secondary:
        body += (
            f"\n🎯 *{secondary['label']} FORECAST*\n"
            f"   Probability: `{secondary['prob']*100:.1f}%`\n"
            f"   Confidence: `{secondary['conf']*100:.0f}%`\n"
        )
    body += f"\n📈 *Regime*: {result['trend_regime']} · Vol: {result['vol_regime']}\n"

    if result["entry_levels"]:
        e = result["entry_levels"]
        body += (
            f"{sep}\n"
            f"💰 *Entry Plan*\n"
            f"   Entry: `{_price(e['entry'], result['market'])}`\n"
            f"   TP1:   `{_price(e['tp1'], result['market'])}` (R:R `{e['rr1']:.1f}`)\n"
            f"   TP2:   `{_price(e['tp2'], result['market'])}` (R:R `{e['rr2']:.1f}`)\n"
            f"   SL:    `{_price(e['sl'], result['market'])}`\n"
        )
    body += (
        f"{sep}\n"
        f"⚡ _Mesin Entry v1.1 · {result['tf_label']}_\n"
        f"⚠️ _Probabilistik, BUKAN guarantee!_"
    )

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": body, "parse_mode": "Markdown"},
            timeout=10
        )
        if r.status_code == 200:
            return True, "Terkirim ✅"
        return False, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"

# ════════════════════════════════════════════════════════════════════
#  STREAMLIT UI
# ════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .stApp { background: #0a0e1a; color: #e2e8f0; font-family: 'Space Mono', monospace; }
    .main .block-container { padding-top: 1.5rem; max-width: 1400px; }
    h1, h2, h3, h4 { font-family: 'Space Mono', monospace; color: #e2e8f0; }
    .hdr-card {
        background: linear-gradient(135deg, #0d1421, #131b2e);
        border: 1px solid #1c2533; border-radius: 8px;
        padding: 16px 20px; margin-bottom: 16px;
    }
    .gauge-card {
        background: #0d1421; border: 1px solid #1c2533;
        border-radius: 8px; padding: 24px; text-align: center; height: 100%;
    }
    .tf-row { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid #1a2030; }
    .tf-label { width: 50px; font-size: 11px; color: #8b95a8; font-weight: 700; }
    .tf-bar-bg { flex: 1; height: 12px; background: #1a2030; border-radius: 2px; position: relative; overflow: hidden; }
    .tf-bar-fill { height: 100%; transition: width 0.3s; }
    .tf-value { width: 80px; font-size: 11px; text-align: right; font-weight: 700; }
    .entry-card { background: linear-gradient(135deg, #0d1421, #0a1a10); border: 1px solid #1c4a2d; border-radius: 8px; padding: 16px; }
    .entry-card.short { background: linear-gradient(135deg, #0d1421, #1a0a0d); border: 1px solid #4a1c2d; }
    .entry-card.wait { background: linear-gradient(135deg, #0d1421, #1a1a0a); border: 1px solid #4a4a1c; }
    .knn-table { width: 100%; border-collapse: collapse; }
    .knn-table th { background: #131b2e; color: #8b95a8; padding: 8px 10px; text-align: left; font-size: 10px; font-weight: 700; border-bottom: 1px solid #1c2533; }
    .knn-table td { padding: 6px 10px; font-size: 11px; border-bottom: 1px solid #131b2e; }
    .pill { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 700; border: 1px solid; margin: 2px; }
    .disclaimer { background: #1a1500; border: 1px solid #4a4000; color: #ffb700; padding: 12px 16px; border-radius: 6px; font-size: 11px; margin-top: 16px; }
</style>
""", unsafe_allow_html=True)

for k in ["last_result", "last_ticker", "last_scan_time"]:
    if k not in st.session_state: st.session_state[k] = None

st.markdown("""
<div class="hdr-card">
    <div style="display:flex; align-items:center; justify-content:space-between;">
        <div>
            <div style="font-size:22px; font-weight:700; color:#00ff88;">🎯 MESIN ENTRY v1.1</div>
            <div style="font-size:11px; color:#8b95a8; margin-top:2px;">
                Probabilistic Entry Timing · Multi-style timeframes · Section 18.2 + 3.17 + 3.20
            </div>
        </div>
        <div style="text-align:right; font-size:11px; color:#8b95a8;">
            <div>Scalping ⚡ · Intraday 📊 · Swing 🎯 · Position 📈 · Bagger 💎</div>
            <div>IDX · US · Crypto · FX · Commodity</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ─── TABS: SINGLE TICKER vs IDX/US/CRYPTO MULTI-SCAN ─────────────
def render_market_scan_tab(market_key):
    """Render multi-scan UI for given market (IDX/US/Crypto). Uses MARKET_CONFIGS."""
    mcfg = MARKET_CONFIGS[market_key]
    n_total = len(mcfg["tickers"])
    flag = mcfg["flag"]
    market_name = mcfg["name"]
    cur_fn = mcfg["currency_fn"]
    unit = "saham" if market_key in ("IDX", "US") else "coins"
    st.markdown(f"""
    <div style="background: linear-gradient(135deg,#1a0d2e,#0d1421); border:1px solid #4a1c7a; border-radius:8px; padding:14px 18px; margin-bottom:14px;">
        <div style="font-size:16px; font-weight:700; color:#bf5fff;">{flag} {market_name} Multi-Scan — {n_total} {unit}</div>
        <div style="font-size:11px; color:#8b95a8; margin-top:4px;">
            Apply Mesin Entry engine ke seluruh universe {market_name}. Pilih mode:<br>
            <strong style="color:#00ff88;">⚡ Quick Scan</strong> — single TF (1-2 menit) ·
            <strong style="color:#bf5fff;">★ Multi-TF Decision</strong> — 1H+15m+5m confluence (3-4 menit, lebih akurat)
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Mode selector
    mc1, mc2 = st.columns([2, 5])
    with mc1:
        sc_mode = st.radio(
            "Scan Mode",
            ["⚡ Quick (Single TF)", "★ Multi-TF Decision"],
            index=1,  # default to Multi-TF
            horizontal=False,
            key=f"{market_key}_mode",
            help="Multi-TF: 1H bias + 15m trigger + 5m execution → confluence score dengan stars rating"
        )
    is_multi_tf = sc_mode.startswith("★")

    with mc2:
        if is_multi_tf:
            st.markdown("""
            <div style="background:#0d1421; border:1px solid #4a1c7a; border-radius:6px; padding:10px 14px; margin-top:24px; font-size:11px;">
                <strong style="color:#bf5fff;">★★★★ Multi-TF Decision logic:</strong><br>
                • 1H weight 45% (BIAS) · 15m weight 35% (TRIGGER) · 5m weight 20% (EXECUTION)<br>
                • ★★★★ STRONG: all 3 TFs aligned + score ≥65 · ★★★ VALID: ≥2 aligned + score ≥50<br>
                • ★★ MONITOR: partial · ★ WEAK: marginal · ✗ WAIT: skip
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background:#0d1421; border:1px solid #1c4a2d; border-radius:6px; padding:10px 14px; margin-top:24px; font-size:11px;">
                <strong style="color:#00ff88;">⚡ Quick Single-TF Mode:</strong><br>
                Analisa cuma 1 timeframe (cepat ~1-2 menit). Pakai mode ini buat pre-screen.
                Setelah dapat kandidat, switch ke Multi-TF buat konfirmasi.
            </div>
            """, unsafe_allow_html=True)

    # Multi-TF Coverage selector (only relevant in multi-TF mode)
    if is_multi_tf:
        # Build option labels with actual market values
        opt_100 = "⚡ Top 100 (~2 menit)"
        opt_300 = "📊 Top 300 (~5 menit)"
        opt_500 = "🔥 Top 500 (~8 menit)"
        opt_all = f"💎 ALL {n_total} {unit} (~15 menit)"
        cov_label = st.radio(
            "Stage 2 Coverage — berapa kandidat dari Stage 1 yang di-deep-dive multi-TF",
            [opt_100, opt_300, opt_500, opt_all],
            index=0, horizontal=True, key=f"{market_key}_coverage",
            help=f"Stage 1 selalu scan semua {n_total}. Stage 2 (multi-TF) cuma deep-dive top N kandidat dari Stage 1. Lebih banyak = lebih komprehensif tapi lebih lama."
        )
        coverage_map = {
            opt_100: 100,
            opt_300: 300,
            opt_500: 500,
            opt_all: n_total,
        }
        sc_coverage_n = coverage_map[cov_label]
    else:
        sc_coverage_n = 100  # not used in quick mode

    # Settings row
    ic1, ic2, ic3, ic4, ic5 = st.columns([2, 2, 2, 1, 1.5])
    with ic1:
        if is_multi_tf:
            st.markdown("<br>", unsafe_allow_html=True)
            st.caption("**TFs analyzed:** 1H · 15m · 5m (fixed)")
            sc_tf = "15m"  # used for stage 1 pre-screen
        else:
            sc_tf = st.selectbox("Timeframe", list(TF_CONFIG.keys()), index=1, key=f"{market_key}_tf",
                help="Entry timeframe. 15m=intraday, 1h=swing, 1d=position, 1wk=bagger")
    with ic2:
        if is_multi_tf:
            sc_min_stars = st.slider("Min Stars", 1, 4, 2, key=f"{market_key}_min_stars",
                help="Filter: hanya tampilkan signal dengan ≥N stars")
            sc_min_prob = 0.55  # stage 1 threshold (semi-permissive)
        else:
            sc_min_prob = st.slider("Min Probability", 0.55, 0.85, 0.60, 0.05, key=f"{market_key}_mp",
                help="Filter: tampilkan signal dengan P(direction) >= ini")
            sc_min_stars = 0
    with ic3:
        sc_dir = st.selectbox("Direction", ["ALL", "LONG", "SHORT"], index=0, key=f"{market_key}_dir")
    with ic4:
        sc_k = st.slider("KNN k", 5, 30, 20, key=f"{market_key}_k")
    with ic5:
        st.markdown("<br>", unsafe_allow_html=True)
        scan_btn_label = "★ MULTI-TF SCAN" if is_multi_tf else f"🔥 SCAN ALL {market_name.upper()}"
        sc_scan_btn = st.button(scan_btn_label, type="primary", use_container_width=True, key=f"{market_key}_scan_btn")

    # Telegram button
    icb1, icb2, _ = st.columns([1.5, 1.5, 5])
    with icb1:
        sc_tg_btn = st.button("📡 Top 10 → Telegram", use_container_width=True, key=f"{market_key}_tg_btn")
    with icb2:
        if st.button("🗑️ Clear results", use_container_width=True, key=f"{market_key}_clear_btn"):
            for k_ in ["{0}_scan_results".format(market_key),"{0}_skip_reasons".format(market_key),"{0}_multi_tf_results".format(market_key),"{0}_multi_tf_stats".format(market_key)]:
                st.session_state.pop(k_, None)

    # Execute scan
    if sc_scan_btn:
        prog = st.progress(0, text="Initializing scan...")
        def _pcb(done, total, phase):
            # Map phase to display text + bar percentage
            if phase.startswith("stage1_"):
                # Stage 1: 0-50% of overall bar
                pct = min((done/total)*0.5, 0.5) if total > 0 else 0
                action = "fetching" if "fetch" in phase else "analyzing"
                text = f"📥 STAGE 1 ({action} all {total} {market_name}): {done}/{total} ({int(done/total*100) if total else 0}%)"
            elif phase == "stage2_multi_tf":
                # Stage 2: 50-100% of overall bar
                pct = 0.5 + min((done/total)*0.5, 0.5) if total > 0 else 0.5
                text = f"★ STAGE 2 multi-TF: {done}/{total} candidates ({int(done/total*100) if total else 0}%)"
            elif phase in ("fullscan_multi_tf", "fullscan_init"):
                # Full universe mode: single 0-100% bar
                pct = done/total if total > 0 else 0
                text = f"💎 FULL UNIVERSE multi-TF: {done}/{total} ({int(done/total*100) if total else 0}%)"
            elif phase in ("fetching", "analyzing"):
                # Quick (single-TF) mode
                pct = done/total if total > 0 else 0
                action = "FETCH" if phase == "fetching" else "ANALYZE"
                text = f"📥 {action}: {done}/{total} ({int(done/total*100) if total else 0}%)"
            else:
                pct = done/total if total else 0
                text = f"{phase}: {done}/{total}"
            prog.progress(pct, text=text)

        if is_multi_tf:
            with st.spinner("Multi-TF Scan: 2-stage analysis (1H + 15m + 5m)..."):
                res, stats = scan_market_multi_tf(market_key=market_key, 
                    stage1_min_prob=0.52, top_n_stage2=sc_coverage_n, k=sc_k,
                    min_stars=sc_min_stars, direction_filter=sc_dir,
                    workers=6, progress_cb=_pcb
                )
                st.session_state["{0}_multi_tf_results".format(market_key)] = res
                st.session_state["{0}_multi_tf_stats".format(market_key)] = stats
                st.session_state["{0}_scan_time".format(market_key)] = time.time()
                st.session_state.pop("{0}_scan_results".format(market_key), None)  # clear single-TF results
        else:
            with st.spinner(f"Scanning {n_total} {market_name} on {sc_tf}..."):
                res, skip = scan_market_universe(market_key=market_key, 
                    timeframe=sc_tf, k=sc_k, min_prob=sc_min_prob,
                    direction_filter=sc_dir, workers=6, progress_cb=_pcb
                )
                st.session_state["{0}_scan_results".format(market_key)] = res
            st.session_state["{0}_skip_reasons".format(market_key)] = skip
            st.session_state["{0}_scan_tf".format(market_key)] = sc_tf
            st.session_state["{0}_scan_time".format(market_key)] = time.time()
        prog.empty()

    # Display results — branch based on mode
    sc_results = st.session_state.get("{0}_scan_results".format(market_key), [])
    sc_skip = st.session_state.get("{0}_skip_reasons".format(market_key), {})
    sc_tf_used = st.session_state.get("{0}_scan_tf".format(market_key), sc_tf)
    mtf_results = st.session_state.get("{0}_multi_tf_results".format(market_key), [])
    mtf_stats = st.session_state.get("{0}_multi_tf_stats".format(market_key), {})

    # Telegram dispatch
    if sc_tg_btn:
        if mtf_results:
            ok, msg = send_telegram_multi_tf_batch(mtf_results[:10], market_key=market_key)
            if ok: st.success(f"Telegram: {msg}")
            else:  st.error(f"Telegram: {msg}")
        elif sc_results:
            ok, msg = send_telegram_idx_batch(sc_results[:10], sc_tf_used, market_key=market_key)
            if ok: st.success(f"Telegram: {msg}")
            else:  st.error(f"Telegram: {msg}")
        else:
            st.warning("Scan dulu sebelum kirim Telegram bro")

    # ═══ MULTI-TF RESULTS DISPLAY ═══
    if mtf_results:
        n_long = sum(1 for r in mtf_results if r["multi_tf"]["direction"]=="LONG")
        n_short = sum(1 for r in mtf_results if r["multi_tf"]["direction"]=="SHORT")
        n_4star = sum(1 for r in mtf_results if r["multi_tf"]["stars"]==4)
        n_3star = sum(1 for r in mtf_results if r["multi_tf"]["stars"]==3)
        n_2star = sum(1 for r in mtf_results if r["multi_tf"]["stars"]==2)

        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1a0d2e,#0d1421); border:1px solid #4a1c7a; border-radius:6px; padding:10px 14px; margin-bottom:10px; font-size:12px;">
            <strong style="color:#bf5fff;">★ Multi-TF Decision Results</strong> · {len(mtf_results)} signals ·
            <span style="color:#00ff88;">🟢 {n_long} LONG</span> ·
            <span style="color:#ff3d5a;">🔴 {n_short} SHORT</span> ·
            <span style="color:#ffb700;">★★★★ {n_4star}</span> ·
            <span style="color:#4da6ff;">★★★ {n_3star}</span> ·
            <span style="color:#8b95a8;">★★ {n_2star}</span>
        </div>
        """, unsafe_allow_html=True)

        # Multi-TF result table
        table_rows = ""
        for i, r in enumerate(mtf_results[:50]):
            m = r["multi_tf"]
            tfs = r["tf_results"]
            stars_disp = "★" * m["stars"] + "<span style='color:#1c2533;'>" + "★" * (4-m["stars"]) + "</span>"
            dir_col = "#00ff88" if m["direction"]=="LONG" else "#ff3d5a" if m["direction"]=="SHORT" else "#ffb700"
            dir_emoji = "🟢" if m["direction"]=="LONG" else "🔴" if m["direction"]=="SHORT" else "⚪"
            chg_col = "#00ff88" if r["change_pct"]>=0 else "#ff3d5a"
            chg_sym = "▲" if r["change_pct"]>=0 else "▼"

            # Per-TF direction badges
            def _tf_badge(tf_key):
                tr = tfs.get(tf_key)
                if tr is None: return '<span style="color:#4a5568;">✗</span>'
                if tr["direction"] == "LONG":  return f'<span style="color:#00ff88; font-weight:700;">🟢 {tr["prob"]*100:.0f}</span>'
                if tr["direction"] == "SHORT": return f'<span style="color:#ff3d5a; font-weight:700;">🔴 {(100-tr["prob"]*100):.0f}</span>'
                return f'<span style="color:#ffb700;">⚪ {tr["prob"]*100:.0f}</span>'

            e = r.get("entry")
            entry_str = f"{cur_fn(e["entry"])}" if e else "—"
            tp_str = f"{cur_fn(e["tp1"])}" if e else "—"
            sl_str = f"{cur_fn(e["sl"])}" if e else "—"
            rr_str = f"{e['rr1']:.2f}" if e else "—"

            table_rows += (
                f'<tr>'
                f'<td style="color:#4a5568; text-align:center;">{i+1}</td>'
                f'<td style="color:#ffb700; font-size:13px;">{stars_disp}</td>'
                f'<td style="color:#e2e8f0; font-weight:700;">{r["ticker"]}</td>'
                f'<td style="text-align:right; color:#e2e8f0;">{cur_fn(r["price"])}</td>'
                f'<td style="text-align:right; color:{chg_col};">{chg_sym} {abs(r["change_pct"]):.2f}%</td>'
                f'<td style="text-align:center; color:{dir_col}; font-weight:700;">{dir_emoji} {m["label"]}</td>'
                f'<td style="text-align:right; color:{dir_col}; font-weight:700;">{m["score"]:.0f}</td>'
                f'<td style="text-align:center;">{_tf_badge("1h")}</td>'
                f'<td style="text-align:center;">{_tf_badge("15m")}</td>'
                f'<td style="text-align:center;">{_tf_badge("5m")}</td>'
                f'<td style="text-align:right; color:#e2e8f0;">{entry_str}</td>'
                f'<td style="text-align:right; color:#00ff88;">{tp_str}</td>'
                f'<td style="text-align:right; color:#ff3d5a;">{sl_str}</td>'
                f'<td style="text-align:center; color:#8b95a8;">{rr_str}</td>'
                f'<td style="text-align:center; color:#4a5568; font-size:10px;">{r["trend"]}</td>'
                f'</tr>'
            )
        st.markdown(
            '<table class="knn-table" style="margin-top:8px;">'
            '<tr>'
            '<th style="width:30px;">#</th>'
            '<th style="width:70px;">Stars</th>'
            '<th>Ticker</th>'
            '<th style="text-align:right;">Price</th>'
            '<th style="text-align:right;">Chg%</th>'
            '<th style="text-align:center;">Decision</th>'
            '<th style="text-align:right;">Score</th>'
            '<th style="text-align:center;">1H</th>'
            '<th style="text-align:center;">15m</th>'
            '<th style="text-align:center;">5m</th>'
            '<th style="text-align:right;">Entry</th>'
            '<th style="text-align:right;">TP1</th>'
            '<th style="text-align:right;">SL</th>'
            '<th style="text-align:center;">R:R</th>'
            '<th style="text-align:center;">Trend</th>'
            '</tr>' + table_rows + '</table>',
            unsafe_allow_html=True
        )
        if len(mtf_results) > 50:
            st.caption(f"Showing top 50 of {len(mtf_results)} signals (sorted by multi-TF score)")

        # Stats
        with st.expander("📊 Multi-TF scan breakdown"):
            mode_label = "💎 FULL UNIVERSE (bypassed Stage 1 filter)" if mtf_stats.get("mode")=="full_universe" else "📊 2-STAGE (Quick pre-screen → Multi-TF confirm)"
            st.markdown(f"""
            **Scan mode:** {mode_label}

            **Stage 1 (15m pre-screen):**
            - Total {market_name} stocks scanned: {mtf_stats.get('stage1_total', 0)}
            - Passed initial threshold: {mtf_stats.get('stage1_passed', 0)}
            - Skip reasons: {mtf_stats.get('stage1_skip', {})}

            **Stage 2 (Multi-TF confirmation):**
            - Candidates analyzed multi-TF: {mtf_stats.get('stage2_candidates', 0)}
            - Passed multi-TF filter (≥ Min Stars): {mtf_stats.get('stage2_passed', 0)}
            - Skip reasons: {mtf_stats.get('stage2_skip', {})}
            """)

    # ═══ SINGLE-TF RESULTS DISPLAY ═══
    elif sc_results:
        # Summary stats
        n_long = sum(1 for r in sc_results if r["direction"] == "LONG")
        n_short = sum(1 for r in sc_results if r["direction"] == "SHORT")
        n_wait = sum(1 for r in sc_results if r["direction"] == "WAIT")
        st.markdown(f"""
        <div style="background:#0d1421; border:1px solid #1c2533; border-radius:6px; padding:10px 14px; margin-bottom:10px; font-size:12px;">
            <strong>{len(sc_results)} signals</strong> lolos filter ·
            <span style="color:#00ff88;">🟢 {n_long} LONG</span> ·
            <span style="color:#ff3d5a;">🔴 {n_short} SHORT</span> ·
            <span style="color:#ffb700;">⚪ {n_wait} WAIT</span>
            · TF: <strong>{sc_tf_used}</strong>
        </div>
        """, unsafe_allow_html=True)

        # Results table
        table_rows = ""
        for i, r in enumerate(sc_results[:50]):  # show top 50
            prob = r["prob"]; conf = r["conf"]
            dir_col = "#00ff88" if r["direction"]=="LONG" else "#ff3d5a" if r["direction"]=="SHORT" else "#ffb700"
            dir_emoji = "🟢" if r["direction"]=="LONG" else "🔴" if r["direction"]=="SHORT" else "⚪"
            chg_col = "#00ff88" if r["change_pct"]>=0 else "#ff3d5a"
            chg_sym = "▲" if r["change_pct"]>=0 else "▼"
            prob_disp = prob*100 if r["direction"]=="LONG" else (100-prob*100) if r["direction"]=="SHORT" else prob*100
            wr_col = "#00ff88" if r["winrate"]>=0.55 else "#ff3d5a" if r["winrate"]<=0.45 else "#ffb700"
            e = r.get("entry")
            entry_str = f"{cur_fn(e["entry"])}" if e else "—"
            tp_str    = f"{cur_fn(e["tp1"])}"   if e else "—"
            sl_str    = f"{cur_fn(e["sl"])}"    if e else "—"
            rr_str    = f"{e['rr1']:.2f}"        if e else "—"
            table_rows += (
                f'<tr>'
                f'<td style="color:#4a5568; text-align:center;">{i+1}</td>'
                f'<td style="color:#e2e8f0; font-weight:700;">{r["ticker"]}</td>'
                f'<td style="text-align:right; color:#e2e8f0;">{cur_fn(r["price"])}</td>'
                f'<td style="text-align:right; color:{chg_col};">{chg_sym} {abs(r["change_pct"]):.2f}%</td>'
                f'<td style="text-align:center; color:{dir_col}; font-weight:700;">{dir_emoji} {r["direction"]}</td>'
                f'<td style="text-align:right; color:{dir_col}; font-weight:700;">{prob_disp:.1f}%</td>'
                f'<td style="text-align:right; color:#8b95a8;">{conf*100:.0f}%</td>'
                f'<td style="text-align:right; color:{wr_col};">{r["winrate"]*100:.0f}%</td>'
                f'<td style="text-align:right; color:#e2e8f0;">{entry_str}</td>'
                f'<td style="text-align:right; color:#00ff88;">{tp_str}</td>'
                f'<td style="text-align:right; color:#ff3d5a;">{sl_str}</td>'
                f'<td style="text-align:center; color:#8b95a8;">{rr_str}</td>'
                f'<td style="text-align:center; color:#4a5568; font-size:10px;">{r["trend"]}</td>'
                f'</tr>'
            )
        st.markdown(
            '<table class="knn-table" style="margin-top:8px;">'
            '<tr>'
            '<th style="width:30px;">#</th>'
            '<th>Ticker</th>'
            '<th style="text-align:right;">Price</th>'
            '<th style="text-align:right;">Chg%</th>'
            '<th style="text-align:center;">Direction</th>'
            f'<th style="text-align:right;">P({sc_tf_used})</th>'
            '<th style="text-align:right;">Conf</th>'
            '<th style="text-align:right;">Win</th>'
            '<th style="text-align:right;">Entry</th>'
            '<th style="text-align:right;">TP1</th>'
            '<th style="text-align:right;">SL</th>'
            '<th style="text-align:center;">R:R</th>'
            '<th style="text-align:center;">Trend</th>'
            '</tr>' + table_rows + '</table>',
            unsafe_allow_html=True
        )
        if len(sc_results) > 50:
            st.caption(f"Showing top 50 of {len(sc_results)} signals (sorted by directional strength)")

        # Skip breakdown
        with st.expander("📊 Skip breakdown (debugging)"):
            st.markdown(f"""
            - **No data / insufficient bars:** {sc_skip.get('no_data',0)}
            - **Feature matrix gagal:** {sc_skip.get('features_fail',0)}
            - **Below min probability:** {sc_skip.get('low_prob',0)}
            - **Wrong direction (filter):** {sc_skip.get('wrong_dir',0)}
            - **Total scanned:** {n_total}
            - **Total signals returned:** {len(sc_results)}
            """)
    else:
        if "{0}_scan_results".format(market_key) in st.session_state or "{0}_multi_tf_results".format(market_key) in st.session_state:
            st.warning("Scan selesai tapi tidak ada signal yang lolos filter. Coba turunkan Min Stars/Probability atau ganti Direction filter.")
        else:
            st.info("👆 Pilih mode (Quick / Multi-TF) lalu klik tombol scan. Multi-TF butuh ~3-4 menit untuk full 981 saham (2-stage analysis).")


tab_single, tab_idx, tab_us, tab_crypto = st.tabs([
    "🎯 Single Ticker Entry",
    "🇮🇩 IDX Multi-Scan (981)",
    "🇺🇸 US Multi-Scan (583)",
    "₿ Crypto Multi-Scan (208)",
])

with tab_single:
    # ─── INPUT ROW ────────────────────────────────────────────────────
    col_t, col_m, col_tf, col_k = st.columns([2.5, 2, 2.5, 1])
    with col_t:
        ticker_raw = st.text_input("Ticker", value="BBCA", key="me_ticker_input",
            help="Cukup ketik kode-nya: BBCA (IDX), AAPL (US), BTC (Crypto), XAUUSD (FX). Suffix akan auto-append.")
    with col_m:
        market = st.selectbox("Market",
            list(MARKET_SUFFIX.keys()), index=0, key="me_market_select",
            help="Auto-append suffix:\n• IDX → .JK\n• Crypto → -USD\n• FX → =X\n• Commodity: smart (XAUUSD→=X spot, GC→=F futures, GLD→ETF as-is)")
    with col_tf:
        tf_options = list(TF_CONFIG.keys())
        tf_display = [f"{tf} — {TF_CONFIG[tf]['label']}" for tf in tf_options]
        tf_choice = st.selectbox("Timeframe (style)", tf_display, index=1, key="me_tf_select")
        primary_tf = tf_choice.split(" — ")[0]
    with col_k:
        k_neighbors = st.slider("KNN k", 5, 50, 20, key="me_knn_slider")

    # Auto-format ticker for display
    ticker_formatted = format_ticker(ticker_raw, market)

    # Check if commodity alias remap happened (for user transparency)
    remap_note = ""
    raw_upper = ticker_raw.strip().upper()
    if market == "Commodity" and raw_upper in COMMODITY_ALIAS:
        remap_note = f' <span style="color:#ffb700; font-size:10px;">⚡ auto-remapped from <code>{raw_upper}</code> — yFinance data lebih reliable di futures</span>'

    st.markdown(f"""
    <div style="font-size:11px; color:#8b95a8; margin-top:-8px;">
        Resolved ticker: <code style="color:#00ff88; background:#0d1421; padding:2px 6px; border-radius:3px;">{ticker_formatted}</code>
        · Default T1 for {primary_tf}: <code style="color:#4da6ff;">{TF_CONFIG[primary_tf]['default_T1']}</code> bars
        {remap_note}
    </div>
    """, unsafe_allow_html=True)

    col_btn1, col_btn2, col_btn3, _ = st.columns([1.5, 1.7, 1.5, 4])
    with col_btn1:
        analyze_btn = st.button("🎯 ANALYZE", type="primary", use_container_width=True, key="me_analyze_btn")
    with col_btn2:
        multi_tf_btn = st.button("★ ANALYZE Multi-TF (1H+15m+5m)", use_container_width=True, key="me_mtf_btn",
                                  help="Run engine on 3 TFs simultaneously, get confluence Decision Score")
    with col_btn3:
        tg_btn = st.button("📡 SEND TELEGRAM", use_container_width=True, key="me_tg_btn")

    if analyze_btn:
        if not ticker_formatted:
            st.error("Ticker tidak boleh kosong bro")
        else:
            with st.spinner(f"Fetching & analyzing {ticker_formatted} on {primary_tf} ({TF_CONFIG[primary_tf]['label']})..."):
                result = analyze_ticker(ticker_formatted, primary_tf=primary_tf, T1=None, k=k_neighbors, market=market)
                st.session_state.last_result = result
                st.session_state.last_ticker = ticker_formatted
                st.session_state.last_scan_time = time.time()
                st.session_state.pop("last_multi_tf", None)

    if multi_tf_btn:
        if not ticker_formatted:
            st.error("Ticker tidak boleh kosong bro")
        else:
            with st.spinner(f"Multi-TF analysis: fetching 1H + 15m + 5m for {ticker_formatted}..."):
                mtf = analyze_multi_tf(ticker_formatted, k=k_neighbors, market=market)
                st.session_state.last_multi_tf = mtf
                st.session_state.last_ticker = ticker_formatted
                st.session_state.last_scan_time = time.time()

    if tg_btn:
        r = st.session_state.last_result
        if r and not r.get("error"):
            ok, msg = send_telegram(st.session_state.last_ticker, r)
            if ok: st.success(f"Telegram: {msg}")
            else:  st.error(f"Telegram: {msg}")
        else:
            st.warning("Analyze dulu sebelum kirim Telegram bro")

    result = st.session_state.last_result
    mtf_result = st.session_state.get("last_multi_tf")

    # ═══ MULTI-TF DECISION DISPLAY ═══
    if mtf_result and not mtf_result.get("error"):
        ticker_disp = st.session_state.last_ticker
        m = mtf_result["multi_tf"]
        tfs = mtf_result["tf_results"]

        # BIG decision card
        stars_filled = "★" * m["stars"]
        stars_empty = "<span style='color:#1c2533;'>" + "★" * (4 - m["stars"]) + "</span>"
        dir_emoji = "🟢" if m["direction"]=="LONG" else "🔴" if m["direction"]=="SHORT" else "⚪"
        chg_col = "#00ff88" if mtf_result["change_pct"]>=0 else "#ff3d5a"
        chg_sym = "▲" if mtf_result["change_pct"]>=0 else "▼"

        st.markdown(
            f'<div style="background:linear-gradient(135deg, #0d1421, {m["color"]}15); '
            f'border:2px solid {m["color"]}; border-radius:10px; padding:18px 22px; margin-bottom:14px;">'
            f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">'
            f'<div>'
            f'<div style="font-size:11px; color:#8b95a8; letter-spacing:1px; font-weight:700;">★ MULTI-TF DECISION · {ticker_disp}</div>'
            f'<div style="font-size:28px; color:#ffb700; margin:6px 0; letter-spacing:2px;">{stars_filled}{stars_empty}</div>'
            f'<div style="font-size:22px; font-weight:700; color:{m["color"]};">{dir_emoji} {m["label"]}</div>'
            f'<div style="font-size:11px; color:#8b95a8; margin-top:6px;">'
            f'Score: <strong style="color:#e2e8f0;">{m["score"]:.1f}/100</strong> · '
            f'Agreement: <strong style="color:#e2e8f0;">{m["agreement"]*100:.0f}%</strong> · '
            f'Confidence: <strong style="color:#e2e8f0;">{m["avg_conf"]*100:.0f}%</strong>'
            f'</div></div>'
            f'<div style="text-align:right;">'
            f'<div style="font-size:24px; font-weight:700; color:#e2e8f0;">{_price(mtf_result["price"], mtf_result["market"])}</div>'
            f'<div style="font-size:13px; color:{chg_col}; font-weight:700;">{chg_sym} {abs(mtf_result["change_pct"]):.2f}%</div>'
            f'<div style="font-size:10px; color:#8b95a8; margin-top:4px;">ATR(14): {_price(mtf_result["atr"], mtf_result["market"])}</div>'
            f'<div style="font-size:10px; color:#8b95a8; margin-top:2px;">Regime: <span style="color:{mtf_result["trend_color"]}">{mtf_result["trend_regime"]}</span> · Vol: <span style="color:{mtf_result["vol_color"]}">{mtf_result["vol_regime"]}</span></div>'
            f'</div>'
            f'</div></div>',
            unsafe_allow_html=True
        )

        # Per-TF breakdown gauges
        st.markdown("### 🎚 Per-Timeframe Analysis (BIAS → TRIGGER → EXECUTION)")
        mc1, mc2, mc3 = st.columns(3)

        def render_tf_gauge(tf_name, role):
            tr = tfs.get(tf_name)
            if tr is None:
                return (
                    f'<div class="gauge-card" style="border-color:#4a556840;">'
                    f'<div style="font-size:10px; color:#4a5568; font-weight:700;">{role}</div>'
                    f'<div style="font-size:18px; color:#8b95a8; margin:12px 0;">{tf_name.upper()}</div>'
                    f'<div style="font-size:14px; color:#4a5568;">✗ No data</div>'
                    f'</div>'
                )
            prob = tr["prob"]; pct = prob * 100
            if prob >= 0.60:
                color = "#00ff88"; bg = "#0a1a10"; dir_text = "🟢 LONG"
            elif prob <= 0.40:
                color = "#ff3d5a"; bg = "#1a0a0d"; dir_text = "🔴 SHORT"
            else:
                color = "#ffb700"; bg = "#1a1500"; dir_text = "⚪ WAIT"
            return (
                f'<div class="gauge-card" style="background:linear-gradient(135deg, #0d1421, {bg}); border-color:{color}40;">'
                f'<div style="font-size:9px; color:#bf5fff; font-weight:700; letter-spacing:1px;">▼ {role}</div>'
                f'<div style="font-size:11px; color:#8b95a8; font-weight:700; margin-top:3px;">{tf_name.upper()} FORECAST</div>'
                f'<div style="font-size:38px; font-weight:700; color:{color}; margin:10px 0;">{pct:.1f}%</div>'
                f'<div style="font-size:13px; color:{color}; font-weight:700;">{dir_text}</div>'
                f'<div style="font-size:10px; color:#8b95a8; margin-top:8px;">'
                f'Conf <span style="color:#e2e8f0; font-weight:700;">{tr["conf"]*100:.0f}%</span> · '
                f'Win <span style="color:#e2e8f0; font-weight:700;">{tr["winrate"]*100:.0f}%</span></div>'
                f'<div style="margin-top:10px; height:6px; background:#1a2030; border-radius:3px; overflow:hidden;">'
                f'<div style="height:100%; width:{pct}%; background:{color};"></div>'
                f'</div></div>'
            )

        with mc1: st.markdown(render_tf_gauge("1h", "BIAS · 45%"), unsafe_allow_html=True)
        with mc2: st.markdown(render_tf_gauge("15m", "TRIGGER · 35%"), unsafe_allow_html=True)
        with mc3: st.markdown(render_tf_gauge("5m", "EXECUTION · 20%"), unsafe_allow_html=True)

        # Entry plan (only if direction is LONG or SHORT)
        if mtf_result["entry"]:
            e = mtf_result["entry"]
            st.markdown("### 💰 Entry Plan (from 15m execution)")
            css_class = "entry-card"
            if e["direction"] == "SHORT": css_class += " short"
            dir_color = "#00ff88" if e["direction"] == "LONG" else "#ff3d5a"
            dir_emoji2 = "🟢" if e["direction"] == "LONG" else "🔴"
            st.markdown(f"""
            <div class="{css_class}">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <div style="font-size:16px; font-weight:700; color:{dir_color};">{dir_emoji2} {e['direction']} · Multi-TF confirmed</div>
                    <div style="font-size:11px; color:#8b95a8;">ATR(14) = {_price(e['atr'], mtf_result['market'])} · TP2 adaptif by 15m prob</div>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:12px;">
                    <div><div style="font-size:10px; color:#8b95a8;">ENTRY</div><div style="font-size:18px; font-weight:700; color:#e2e8f0;">{_price(e['entry'], mtf_result['market'])}</div></div>
                    <div><div style="font-size:10px; color:#00ff88;">TP1 (1.0× ATR)</div><div style="font-size:18px; font-weight:700; color:#00ff88;">{_price(e['tp1'], mtf_result['market'])}</div><div style="font-size:10px; color:#8b95a8;">R:R {e['rr1']:.2f}</div></div>
                    <div><div style="font-size:10px; color:#00ff88;">TP2 (adaptif)</div><div style="font-size:18px; font-weight:700; color:#00ff88;">{_price(e['tp2'], mtf_result['market'])}</div><div style="font-size:10px; color:#8b95a8;">R:R {e['rr2']:.2f}</div></div>
                    <div><div style="font-size:10px; color:#ff3d5a;">SL (1.0× ATR)</div><div style="font-size:18px; font-weight:700; color:#ff3d5a;">{_price(e['sl'], mtf_result['market'])}</div></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="padding:16px; background:#1a1500; border:1px solid #4a4000; border-radius:6px; color:#ffb700; font-size:12px;">'
                f'⚪ <strong>WAIT — No entry recommended</strong>. Multi-TF tidak align ({m["agreement"]*100:.0f}% agreement). '
                f'Tunggu sampai 1H + 15m + 5m setuju arah yang sama.'
                f'</div>',
                unsafe_allow_html=True
            )

        # Honest reminder
        st.markdown(
            f'<div class="disclaimer">'
            f'<strong>⚠️ Multi-TF Decision Logic</strong><br>'
            f'★★★★ STRONG = all 3 TFs aligned · score ≥65 · agreement 100%<br>'
            f'★★★ VALID = ≥2 TFs aligned · score ≥50 · agreement ≥66%<br>'
            f'★★ MONITOR / ★ WEAK / ✗ WAIT = skip, no entry<br><br>'
            f'<strong>Current breakdown:</strong> 1H BIAS · 15m TRIGGER · 5m EXECUTION → Score {m["score"]:.1f}, {m["label"]}.<br>'
            f'<strong>Realistic accuracy:</strong> 60-68% trending market, 52-55% chop. Position sizing & risk management tetap tanggung jawab lo.'
            f'</div>',
            unsafe_allow_html=True
        )

        # Show "Switch to single-TF mode" hint
        st.caption("💡 Buat deep dive 1 timeframe specific, klik **🎯 ANALYZE** dengan TF pilihan di atas.")

    elif mtf_result and mtf_result.get("error"):
        st.error(f"⚠️ Multi-TF: {mtf_result['error']}")

    elif result is None and mtf_result is None:
        st.info("👆 Pilih ticker, market, timeframe. Klik **ANALYZE**.")
        with st.expander("ℹ️ Style → Timeframe mapping"):
            st.markdown("""
    | Trading Style | Timeframe | Horizon (Forecast) | Use Case |
    |---|---|---|---|
    | **Scalping ⚡** | 5m | 5m / 15m / 1h | Quick in-out, target ATR×1 |
    | **Intraday 📊** | 15m / 30m | 15-30m / 1h / 4h | Same-day, multi-touch ATR |
    | **Swing Entry 🎯** | 1h | 1h / 4h / 1d | Multi-day hold |
    | **Swing/Position 📈** | 1d | 1d / 1w / 1mo | Weekly hold |
    | **Bagger 💎** | 1wk | 1w / 1mo / 3mo | Wyckoff accumulation, longer thesis |

    **Auto-suffix per market:**
    - IDX → BBCA → `BBCA.JK`
    - US → AAPL → `AAPL`
    - Crypto → BTC → `BTC-USD`
    - FX → EURUSD → `EURUSD=X`
    - Commodity → GC=F / XAUUSD=X → as-is (already complete format)
            """)

    elif result is not None and result.get("error"):
        st.error(f"⚠️ {result['error']}")

    elif result is not None:
        ticker = st.session_state.last_ticker
        price = result["price"]; change = result["change_pct"]
        chg_col = "#00ff88" if change >= 0 else "#ff3d5a"
        chg_sym = "▲" if change >= 0 else "▼"

        st.markdown(f"""
        <div class="hdr-card">
            <div style="display:flex; align-items:center; justify-content:space-between;">
                <div>
                    <div style="font-size:13px; color:#8b95a8;">CURRENT STATE · TF: <strong style="color:#00ff88">{result['primary_tf']}</strong> ({result['tf_label']})</div>
                    <div style="font-size:24px; font-weight:700; color:#e2e8f0; margin-top:4px;">
                        {ticker} · {_price(price, result['market'])}
                        <span style="font-size:14px; color:{chg_col}; font-weight:700; margin-left:8px;">{chg_sym} {abs(change):.2f}%</span>
                    </div>
                    <div style="font-size:11px; color:#8b95a8; margin-top:6px;">
                        {result['n_bars']} bars · ATR(14): {_price(result['atr'], result['market'])} · {result['n_features']} valid features · T1={result['T1_used']}{result['t1_note']} · k={result['k_used']}
                    </div>
                </div>
                <div style="text-align:right;">
                    <div><span class="pill" style="color:{result['trend_color']}; border-color:{result['trend_color']}40; background:{result['trend_color']}15;">{result['trend_regime']}</span></div>
                    <div style="margin-top:6px;"><span class="pill" style="color:{result['vol_color']}; border-color:{result['vol_color']}40; background:{result['vol_color']}15;">VOL: {result['vol_regime']}</span></div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # PROBABILITY GAUGES — DYNAMIC per timeframe
        st.markdown("### 🎯 Probability Forecast")
        forecasts = result["forecasts"]
        cols = st.columns(len(forecasts))

        def render_gauge(fc, is_primary=False):
            prob = fc["prob"]; conf = fc["conf"]; direction = fc["direction"]
            pct = prob * 100; cnf = conf * 100
            if prob >= 0.60:
                color = "#00ff88"; bg = "#0a1a10"; dir_text = "🟢 LONG"
            elif prob <= 0.40:
                color = "#ff3d5a"; bg = "#1a0a0d"; dir_text = "🔴 SHORT"
            else:
                color = "#ffb700"; bg = "#1a1500"; dir_text = "⚪ WAIT"
            primary_badge = '<div style="font-size:9px; color:#00ff88; font-weight:700; margin-bottom:4px;">▼ PRIMARY ENTRY</div>' if is_primary else ''
            return (
                f'<div class="gauge-card" style="background: linear-gradient(135deg, #0d1421, {bg}); border-color: {color}40;">'
                f'{primary_badge}'
                f'<div style="font-size:11px; color:#8b95a8; font-weight:700;">{fc["label"]} FORECAST</div>'
                f'<div style="font-size:42px; font-weight:700; color:{color}; margin:12px 0;">{pct:.1f}%</div>'
                f'<div style="font-size:14px; color:{color}; font-weight:700; margin-bottom:6px;">{dir_text}</div>'
                f'<div style="font-size:10px; color:#8b95a8;">'
                f'Confidence: <span style="color:#e2e8f0; font-weight:700;">{cnf:.0f}%</span>'
                f' · Win: <span style="color:#e2e8f0; font-weight:700;">{fc["winrate"]*100:.0f}%</span>'
                f'</div>'
                f'<div style="margin-top:12px; height:6px; background:#1a2030; border-radius:3px; overflow:hidden;">'
                f'<div style="height:100%; width:{pct}%; background:{color};"></div>'
                f'</div>'
                f'</div>'
            )

        for i, (col, fc) in enumerate(zip(cols, forecasts)):
            with col:
                st.markdown(render_gauge(fc, is_primary=(i==0)), unsafe_allow_html=True)

        # MULTI-TF AGREEMENT — DYNAMIC labels
        st.markdown("### 📊 Multi-Horizon Feature Agreement")
        col_tf, col_cb = st.columns([1, 1])

        with col_tf:
            st.markdown(f"<div style='font-size:11px; color:#8b95a8; margin-bottom:8px;'>Sub-scores per τ-horizon (relative to {result['primary_tf']} entry)</div>", unsafe_allow_html=True)
            bars_html = ""
            for tau, b in result["breakdown"].items():
                score = b["sub_score"]
                if score >= 0:
                    bar_color = "#00ff88" if score >= 50 else "#4da6ff" if score >= 20 else "#8b95a8"
                    left = 50; width = abs(score) / 2
                else:
                    bar_color = "#ff3d5a" if score <= -50 else "#ff7b00" if score <= -20 else "#8b95a8"
                    left = 50 - abs(score) / 2; width = abs(score) / 2
                sign = "+" if score >= 0 else ""
                bars_html += (
                    f'<div class="tf-row">'
                    f'<div class="tf-label">{b["label"]}</div>'
                    f'<div class="tf-bar-bg">'
                    f'<div style="position:absolute; left:50%; top:0; width:1px; height:100%; background:#8b95a8;"></div>'
                    f'<div class="tf-bar-fill" style="position:absolute; left:{left}%; width:{width}%; height:100%; background:{bar_color};"></div>'
                    f'</div>'
                    f'<div class="tf-value" style="color:{bar_color};">{sign}{score:.0f}</div>'
                    f'</div>'
                )
            st.markdown(bars_html, unsafe_allow_html=True)
            comp_color = "#00ff88" if result["composite_score"] >= 20 else "#ff3d5a" if result["composite_score"] <= -20 else "#ffb700"
            st.markdown(f"""
            <div style="margin-top:14px; padding-top:10px; border-top:1px solid #1c2533;">
                <div style="display:flex; justify-content:space-between; font-size:11px;">
                    <span style="color:#8b95a8; font-weight:700;">COMPOSITE</span>
                    <span style="color:{comp_color}; font-weight:700;">{result['composite_score']:+.1f} · Agreement {result['score_conf']*100:.0f}%</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col_cb:
            st.markdown("<div style='font-size:11px; color:#8b95a8; margin-bottom:8px;'>Confluence breakdown</div>", unsafe_allow_html=True)
            for tau, b in result["breakdown"].items():
                rsi_v = b["rsi_raw"]
                rsi_label = "OVERSOLD" if rsi_v < 0.3 else "OVERBOUGHT" if rsi_v > 0.7 else "NEUTRAL"
                rsi_col = "#00ff88" if rsi_v < 0.3 else "#ff3d5a" if rsi_v > 0.7 else "#8b95a8"
                ema_dir = "↗" if b["ema_raw"] > 0 else "↘"
                ema_col = "#00ff88" if b["ema_raw"] > 0 else "#ff3d5a"
                st.markdown(
                    f'<div style="background:#0d1421; border:1px solid #1c2533; border-radius:4px; padding:8px 12px; margin-bottom:6px;">'
                    f'<div style="display:flex; justify-content:space-between; font-size:11px;">'
                    f'<span style="color:#e2e8f0; font-weight:700;">{b["label"]}</span>'
                    f'<span style="color:{ema_col}; font-weight:700;">{ema_dir} EMA: {b["ema_raw"]:+.3f}</span>'
                    f'</div>'
                    f'<div style="display:flex; justify-content:space-between; font-size:10px; color:#8b95a8; margin-top:3px;">'
                    f'<span>Mom: {b["momentum"]:+.0f} · Trend: {b["trend"]:+.0f}</span>'
                    f'<span style="color:{rsi_col};">RSI z: {rsi_v:.2f} {rsi_label}</span>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

        # KNN MATCHES — uses PRIMARY forecast (shortest horizon)
        primary = result["forecasts"][0]
        st.markdown(f"### 🔍 KNN Pattern Matches — {primary['label']} horizon")
        knn_wr_col = "#00ff88" if primary['winrate']>=0.55 else "#ff3d5a" if primary['winrate']<=0.45 else "#ffb700"
        st.markdown(f"""
        <div style="font-size:11px; color:#8b95a8; margin-bottom:8px;">
            Top 10 dari {len(primary['knn_idx'])} saat-saat di masa lalu yang paling mirip kondisi sekarang.
            Win rate KNN (next {primary['label']}): <strong style="color:{knn_wr_col};">{primary['winrate']*100:.0f}%</strong>
            · Predicted return: <strong>{primary['knn_pred']*100:+.3f}%</strong>
        </div>
        """, unsafe_allow_html=True)

        knn_rows = ""
        if primary['knn_dist']:
            max_dist = max(primary['knn_dist']); min_dist = min(primary['knn_dist'])
            range_dist = max_dist - min_dist + 1e-9
            for i, (ts, dist, out) in enumerate(zip(primary['knn_idx'][:10], primary['knn_dist'][:10], primary['knn_out'][:10])):
                similarity = 1 - (dist - min_dist) / range_dist
                sim_pct = similarity * 100; out_pct = out * 100
                out_col = "#00ff88" if out > 0 else "#ff3d5a" if out < 0 else "#8b95a8"
                out_sign = "✓" if out > 0 else "✗" if out < 0 else "—"
                try: ts_str = pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")
                except: ts_str = str(ts)
                knn_rows += (
                    f'<tr>'
                    f'<td style="color:#8b95a8;">#{i+1}</td>'
                    f'<td style="color:#e2e8f0; font-family:Space Mono,monospace;">{ts_str}</td>'
                    f'<td style="text-align:right;"><span style="color:#4da6ff; font-weight:700;">{sim_pct:.0f}%</span></td>'
                    f'<td style="text-align:right; color:{out_col}; font-weight:700;">{out_pct:+.3f}%</td>'
                    f'<td style="text-align:center; color:{out_col}; font-weight:700;">{out_sign}</td>'
                    f'</tr>'
                )

        table_html = (
            '<table class="knn-table">'
            '<tr>'
            '<th style="width:40px;">#</th>'
            '<th>Historical Timestamp</th>'
            '<th style="text-align:right; width:80px;">Similarity</th>'
            f'<th style="text-align:right; width:90px;">Outcome ({primary["label"]})</th>'
            '<th style="text-align:center; width:50px;">Win?</th>'
            '</tr>'
            f'{knn_rows}'
            '</table>'
        )
        st.markdown(table_html, unsafe_allow_html=True)

        # ENTRY LEVELS
        if result["entry_levels"]:
            e = result["entry_levels"]
            st.markdown("### 💰 Suggested Entry Plan")
            css_class = "entry-card"
            if e["direction"] == "SHORT": css_class += " short"
            elif e["direction"] == "WAIT": css_class += " wait"
            dir_color = "#00ff88" if e["direction"] == "LONG" else "#ff3d5a" if e["direction"] == "SHORT" else "#ffb700"
            dir_emoji = "🟢" if e["direction"] == "LONG" else "🔴" if e["direction"] == "SHORT" else "⚪"
            st.markdown(f"""
            <div class="{css_class}">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <div style="font-size:16px; font-weight:700; color:{dir_color};">{dir_emoji} {e['direction']} · {primary['label']} horizon</div>
                    <div style="font-size:11px; color:#8b95a8;">ATR(14) = {_price(e['atr'], result['market'])} · TP2 adaptif by probability</div>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:12px;">
                    <div><div style="font-size:10px; color:#8b95a8;">ENTRY</div><div style="font-size:18px; font-weight:700; color:#e2e8f0;">{_price(e['entry'], result['market'])}</div></div>
                    <div><div style="font-size:10px; color:#00ff88;">TP1 (1.0× ATR)</div><div style="font-size:18px; font-weight:700; color:#00ff88;">{_price(e['tp1'], result['market'])}</div><div style="font-size:10px; color:#8b95a8;">R:R {e['rr1']:.2f}</div></div>
                    <div><div style="font-size:10px; color:#00ff88;">TP2 (adaptif)</div><div style="font-size:18px; font-weight:700; color:#00ff88;">{_price(e['tp2'], result['market'])}</div><div style="font-size:10px; color:#8b95a8;">R:R {e['rr2']:.2f}</div></div>
                    <div><div style="font-size:10px; color:#ff3d5a;">SL (1.0× ATR)</div><div style="font-size:18px; font-weight:700; color:#ff3d5a;">{_price(e['sl'], result['market'])}</div></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="padding:16px; background:#1a1500; border:1px solid #4a4000; border-radius:6px; color:#ffb700; font-size:12px;">
                ⚪ <strong>WAIT</strong> — Probabilitas tidak cukup kuat untuk entry. P(UP) antara 40-60%. Tunggu sinyal lebih jelas.
            </div>
            """, unsafe_allow_html=True)

        # HONEST DISCLAIMER
        fc_labels = " / ".join([f['label'] for f in result["forecasts"]])
        st.markdown(f"""
        <div class="disclaimer">
            <strong>⚠️ HONEST EXPECTATION (jangan lupa bro)</strong><br>
            Engine ini probabilistik berdasarkan multi-horizon z-score features + KNN pattern matching dari buku Kakushadze &amp; Serur (2018).<br>
            Forecast horizons: <strong>{fc_labels}</strong> · Style: <strong>{result['tf_label']}</strong><br><br>
            <strong>Realistic accuracy:</strong><br>
            • Trending market (current: <strong>{result['trend_regime']}</strong>): 60-68% directional accuracy<br>
            • Sideways/chop: turun ke 52-55% (mendekati coinflip)<br>
            • News event / black swan: <strong>SEMUA model breakdown</strong> — current vol: <strong style="color:{result['vol_color']}">{result['vol_regime']}</strong><br><br>
            <strong>Position sizing &amp; risk management tetap tanggung jawab lo.</strong> Engine kasih edge probabilistik, BUKAN crystal ball.
        </div>
        """, unsafe_allow_html=True)


with tab_idx:
    render_market_scan_tab("IDX")

with tab_us:
    render_market_scan_tab("US")

with tab_crypto:
    render_market_scan_tab("Crypto")

if st.session_state.last_scan_time:
    lt = datetime.fromtimestamp(st.session_state.last_scan_time, et_tz).strftime("%H:%M:%S ET · %d %b %Y")
    st.markdown(f"<div style='text-align:center; font-size:10px; color:#4a5568; margin-top:24px; font-family:Space Mono,monospace;'>Last analysis: {lt}</div>", unsafe_allow_html=True)
