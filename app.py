import os
import re
import io
import html
import hashlib
import datetime
from typing import Optional, List, Dict, Tuple
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Motech Miami — Price List Manager",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# CONFIG / SCHEMA
# ============================================================
BASE_COLUMNS = [
    "Proveedor", "SKU", "SKU_Fuente", "Descripcion", "Condicion", "Precio", "Stock",
    "Stock_Miami", "Stock_NY", "En_Transito", "MOQ", "ETA", "Ubicacion",
]

MOTIVATIONAL_QUOTES = [
    "🚀 'El éxito en las ventas no es cuestión de suerte, sino de constancia y disciplina.'",
    "💡 'Cada no que recibes te acerca un paso más al sí definitivo.'",
    "🎯 'Enfoque, determinación y excelente atención: la fórmula para superar cualquier meta.'",
    "🔥 'Grandes resultados requieren grandes esfuerzos. ¡Hoy es un excelente día para cerrar tratos!'",
    "⭐ 'El cliente no busca solo un producto, busca la confianza que tú le transmites.'",
]

PROVIDER_CODES = {
    "HAIFA": "HAI",
    "ALL PLUS": "APL",
    "ALLBRANDS": "ABR",
    "AQUA CONSUMER": "AQC",
    "AQUA LAPTOPS": "AQL",
    "ASE": "ASE",
    "CELLUTECH": "CEL",
    "EMOLO": "EMO",
    "H&Z": "HZ",
    "INFLUENTIAL": "INF",
    "PRT": "PRT",
    "SNK": "SNK",
    "SUNRISE": "SUN",
    "TECH SUPPLIER": "TEC",
    "UNLIMITED": "UNL",
    "203_TRADING": "203",
    "WORLDWIDE": "WWD",
}

# ============================================================
# UI STYLE
# ============================================================
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Compacta el espacio superior general */
    .block-container {padding-top: 1.2rem; padding-bottom: 1.5rem;}

    .main-header {font-size:24px;font-weight:800;color:#1B365D;margin:0 0 1px 0;line-height:1.15;}
    .sub-header {font-size:13px;color:#666;margin:0;line-height:1.25;}
    .compact-quote {font-size:12.5px;color:#52606D;font-style:italic;margin-top:5px;line-height:1.25;}

    .kpi-strip {
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:8px;
        margin:8px 0 8px 0;
    }
    .kpi-box {
        border:1px solid #E2E8F0;
        background:#FFFFFF;
        border-radius:8px;
        padding:7px 10px;
        min-width:0;
    }
    .kpi-value {font-size:20px;font-weight:800;color:#1B365D;line-height:1.05;}
    .kpi-label {font-size:11px;color:#667085;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}

    .card-deal {background-color:#E8F5E9;border-left:6px solid #2E7D32;padding:12px 16px;
        border-radius:8px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.08);}
    .card-title {font-size:15px;font-weight:700;color:#1B5E20;margin-bottom:4px;}
    .badge-meta {background-color:#F0F4F8;color:#2D3748;padding:3px 6px;border-radius:4px;
        font-size:12px;margin-right:6px;border:1px solid #CBD5E0;display:inline-block;margin-top:4px;}
    .badge-savings {background-color:#C8E6C9;color:#1B5E20;font-weight:700;padding:3px 8px;
        border-radius:4px;font-size:12px;float:right;}

    div[data-testid="stExpander"] {margin-bottom:6px;}

    @media (max-width: 800px) {
        .kpi-strip {grid-template-columns:repeat(2,minmax(0,1fr));}
        .main-header {font-size:20px;}
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# NORMALIZATION HELPERS
# ============================================================
def _norm_col(x) -> str:
    return re.sub(r"\s+", " ", str(x).strip()).upper()


def clean_price(v) -> Optional[float]:
    if pd.isna(v):
        return None
    s = str(v).strip().upper()
    if not s or any(x in s for x in ["SOLD OUT", "N/A", "CALL", "TBD"]):
        return None
    s = s.replace("$", "").replace(",", "").replace("USD", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        p = float(m.group())
        return p if p > 0 else None
    except Exception:
        return None


def clean_qty(v) -> Optional[float]:
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)) and not pd.isna(v):
        return max(float(v), 0)
    s = str(v).strip().upper().replace(",", "")
    if s in {"", "-", "N/A", "NA", "NONE", "NAN"}:
        return 0.0
    m = re.search(r"\d+(?:\.\d+)?", s)
    return max(float(m.group()), 0) if m else None


def safe_text(v, default="") -> str:
    if pd.isna(v):
        return default
    s = str(v).strip()
    return "" if s.lower() in {"nan", "none"} else s


def synthetic_sku(desc: str, provider: str) -> str:
    digest = hashlib.md5(desc.upper().encode("utf-8", errors="ignore")).hexdigest()[:10].upper()
    return f"{PROVIDER_CODES.get(provider, 'UNK')}-AUTO-{digest}"


def infer_sku_from_description(desc: str, provider: str) -> Tuple[str, str]:
    text = safe_text(desc).upper()
    # Common manufacturer/model/MPN patterns. Avoid obvious capacity/spec tokens.
    tokens = re.findall(r"\b[A-Z0-9][A-Z0-9#./_-]{4,30}\b", text)
    bad = re.compile(r"^(?:\d+(?:GB|TB|HZ|W)|WIN(?:DOWS)?11|DDR\d|LPDDR\d|RTX|WUXGA|FHD|OLED|IPS)$")
    candidates = []
    for t in tokens:
        t = t.strip(".,;:()[]{}")
        if bad.match(t):
            continue
        if not re.search(r"[A-Z]", t) or not re.search(r"\d", t):
            continue
        # score model-like tokens higher than specs
        score = 0
        score += 3 if "-" in t or "/" in t or "#" in t else 0
        score += min(len(t), 20) / 20
        if re.search(r"\d{3,}", t): score += 1
        if any(x in t for x in ["GB", "TB", "HZ", "GHZ", "MHZ"]): score -= 3
        candidates.append((score, t))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1], "INFERRED"
    return synthetic_sku(text, provider), "SYNTHETIC"


def first_col(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    normalized = {c: _norm_col(c) for c in df.columns}
    aliases_n = [_norm_col(a) for a in aliases]
    # exact first
    for c, n in normalized.items():
        if n in aliases_n:
            return c
    # then safe substring
    for c, n in normalized.items():
        if any(a in n for a in aliases_n if len(a) >= 4):
            return c
    return None


def header_row(raw: pd.DataFrame, require_price=True, max_rows=25) -> Optional[int]:
    sku_words = ["SKU", "MODEL", "MPN", "PART NUMBER", "PART #", "ITEM", "ITEM NUMBER", "ITEM CODE"]
    price_words = ["PRICE", "COST", "FOB", "CASH", "EXW"]
    desc_words = ["DESCRIPTION", "PRODUCT", "ITEM NAME", "ITEM DESCRIPTION", "PRODUCTS"]
    best = None
    for i in range(min(max_rows, len(raw))):
        vals = [_norm_col(v) for v in raw.iloc[i].tolist() if pd.notna(v)]
        has_sku = any(any(k in v for k in sku_words) for v in vals)
        has_price = any(any(k in v for k in price_words) for v in vals)
        has_desc = any(any(k in v for k in desc_words) for v in vals)
        score = int(has_sku) * 3 + int(has_price) * 3 + int(has_desc) * 2
        if best is None or score > best[0]: best = (score, i, has_price)
    if not best or best[0] < 5 or (require_price and not best[2]):
        return None
    return best[1]


def excel_file(uploaded):
    uploaded.seek(0)
    data = uploaded.read()
    uploaded.seek(0)
    name = uploaded.name.lower()
    if name.endswith(".xls"):
        try:
            import xlrd  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "Para leer archivos .xls (por ejemplo Cellutech) instala xlrd. "
                "Agrega 'xlrd==2.0.1' a requirements.txt."
            ) from e
    return pd.ExcelFile(io.BytesIO(data))


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=BASE_COLUMNS)


def make_row(provider, sku, desc, price, stock=None, stock_miami=None, stock_ny=None,
             transit=None, moq=None, eta="", location="", condition="", sku_source="FILE") -> Optional[dict]:
    p = clean_price(price)
    d = safe_text(desc)
    sku = safe_text(sku).upper()
    if not sku:
        sku, sku_source = infer_sku_from_description(d, provider)
    if not d or p is None:
        return None
    return {
        "Proveedor": provider,
        "SKU": sku,
        "SKU_Fuente": sku_source,
        "Descripcion": d,
        "Condicion": safe_text(condition),
        "Precio": p,
        "Stock": clean_qty(stock),
        "Stock_Miami": clean_qty(stock_miami),
        "Stock_NY": clean_qty(stock_ny),
        "En_Transito": clean_qty(transit),
        "MOQ": clean_qty(moq),
        "ETA": safe_text(eta),
        "Ubicacion": safe_text(location),
    }


def finalize(rows: List[dict]) -> pd.DataFrame:
    if not rows:
        return empty_frame()

    # Build every expected column first so Pandas does not infer an incompatible
    # dtype and later reject assignments (stricter in newer Pandas versions).
    df = pd.DataFrame(rows).reindex(columns=BASE_COLUMNS)

    numeric_cols = [
        "Precio", "Stock", "Stock_Miami", "Stock_NY", "En_Transito", "MOQ"
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Float64")

    text_cols = [
        "Proveedor", "SKU", "SKU_Fuente", "Descripcion", "Condicion", "ETA", "Ubicacion"
    ]
    for c in text_cols:
        df[c] = df[c].where(df[c].notna(), "").astype("string")

    # Prefer explicit Stock; otherwise use Miami + NY where available.
    has_city = df[["Stock_Miami", "Stock_NY"]].notna().any(axis=1)
    needs_stock = df["Stock"].isna() & has_city
    if bool(needs_stock.any()):
        summed = (
            df[["Stock_Miami", "Stock_NY"]]
            .fillna(0)
            .sum(axis=1)
            .astype("Float64")
        )
        df.loc[needs_stock, "Stock"] = summed.loc[needs_stock].to_numpy()

    df["SKU"] = df["SKU"].str.strip().str.upper()

    # Global commercial filters:
    # 1) BONDED inventory must never reach the comparator.
    # 2) Only products with confirmed stock > 0 are shown. Unknown/missing stock is excluded.
    bonded_text = (
        df["SKU"].astype("string").fillna("") + " " +
        df["Descripcion"].astype("string").fillna("") + " " +
        df["Condicion"].astype("string").fillna("")
    ).str.upper()
    df = df[~bonded_text.str.contains("BONDED", regex=False, na=False)]
    df = df[(df["SKU"] != "") & df["Precio"].notna() & df["Stock"].notna() & (df["Stock"] > 0)]
    return df[BASE_COLUMNS].drop_duplicates().reset_index(drop=True)


# ============================================================
# CATEGORY / SPEC EXTRACTION
# ============================================================
def clasificar_categoria(desc, sku, condition=""):
    text = f"{safe_text(desc)} {safe_text(sku)} {safe_text(condition)}".upper()

    # Refurbished has absolute priority regardless of product type.
    refurb_keys = [
        "REFURBISHED", "REFURB", "RENEWED", "RECERTIFIED",
        "RECONDITIONED", "RECONDITION", "CERTIFIED REFURBISHED",
    ]
    if any(k in text for k in refurb_keys):
        return "♻️ REFURBISHED"

    gaming_keys = [
        "PLAYSTATION", "PS5", "PS4", "XBOX", "NINTENDO", "SWITCH", "JOY-CON", "JOYCON",
        "ROG ALLY", "LEGION GO", "STEAM DECK", "META QUEST", "OCULUS",
        "ALIENWARE", "PREDATOR", "OMEN", "VICTUS", "ZEPHYRUS", "CYBORG", "RAIDER",
        "KATANA", "STRIX", "SCAR", "ROG ", " TUF ", "NITRO", "LOQ",
        "GAMING LAPTOP", "GAMING DESKTOP", "GAMING PC", "GAMING HEADSET",
        "GAMING MOUSE", "GAMING KEYBOARD", "LOGITECH G", "HYPERX", "ASTRO",
    ]
    if any(k in text for k in gaming_keys):
        return "🎮 Gaming"

    desktop_keys = [
        "DESKTOP", "ALL IN ONE", "ALL-IN-ONE", " AIO ", "THINKCENTRE", "THINKCENTER",
        "OPTIPLEX", "PRODESK", "ELITEDESK", "THINKSTATION", "MINI PC", "MINI DESKTOP",
        "MICRO PC", "SFF", "SMALL FORM FACTOR", "TOWER", "WORKSTATION", "SERVER", "NUC",
        "PRECISION TOWER", "PRECISION WORKSTATION", "HP Z2", "HP Z4", "HP Z6", "HP Z8",
    ]
    if any(k in text for k in desktop_keys):
        return "🖥️ Desktops & PC"

    laptop_keys = [
        "MACBOOK", "LAPTOP", "NOTEBOOK", "CHROMEBOOK", "ASPIRE", "VIVOBOOK", "ZENBOOK",
        "EXPERTBOOK", "IDEAPAD", "THINKPAD", "LATITUDE", "INSPIRON", "VOSTRO",
        "PROBOOK", "ELITEBOOK", "ZBOOK", "PAVILION", "ENVY", "SPECTRE", "OMNIBOOK",
        "SURFACE LAPTOP", "LG GRAM", "YOGA", "SWIFT", "TRAVELMATE", "DELL PRO ",
    ]
    if any(k in text for k in laptop_keys):
        return "💻 Laptops"

    # Multimedia is intentionally separate from generic accessories.
    multimedia_keys = [
        "SPEAKER", "SPEAKERS", "BLUETOOTH SPEAKER", "SOUNDBAR", "SOUND BAR",
        "HEADPHONE", "HEADPHONES", "EARBUD", "EARBUDS", "AIRPODS", "BEATS",
        "WIRELESS EARBUD", "TRUE WIRELESS", "TWS", "ECHO DOT", "ECHO SHOW", "ALEXA",
        "FIRE TV", "FIRE STICK", "TV STICK", "CHROMECAST", "ROKU", "APPLE TV",
        "STREAMING DEVICE", "MEDIA PLAYER", "SMART TV BOX",
    ]
    if any(k in text for k in multimedia_keys):
        return "🎵 Multimedia"

    if any(k in text for k in ["IPAD", "TABLET", " TAB ", "GALAXY TAB", "SURFACE PRO"]):
        return "📱 Tablets"

    if any(k in text for k in ["MONITOR", "DISPLAY", "144HZ", "165HZ", "180HZ", "240HZ"]):
        return "🖥️ Monitores"

    accessory_keys = [
        "MOUSE", "KEYBOARD", "CABLE", "PENCIL", "STYLUS", "CASE", "COVER", "DOCK",
        "DOCKING", "ADAPTER", "ADAPTOR", "CHARGER", "POWER SUPPLY", "WEBCAM",
        "USB HUB", "HUB ", "BACKPACK", "SLEEVE",
    ]
    if any(k in text for k in accessory_keys):
        return "🎧 Accesorios"

    # Specification fallback for laptop descriptions without a known family name.
    has_cpu = bool(re.search(r"\b(?:CORE\s+(?:ULTRA\s+)?[3579]|I[3579][-\s]|RYZEN(?:\s+AI)?\s+[3579]|SNAPDRAGON\s+X|CELERON|PENTIUM)\b", text))
    has_screen = bool(re.search(r'\b1[1-7](?:\.\d)?\s*(?:INCH|IN|"|″)?\b', text))
    has_memory = bool(re.search(r"\b(?:4|8|12|16|24|32|48|64)\s*GB\b", text))
    if has_cpu and has_screen and has_memory:
        return "💻 Laptops"

    return "📦 Otros / Varios"

def extraer_especificaciones(text):
    t = str(text).upper()
    cpu = "Otro / No especificado"
    cpu_patterns = [
        (r"\bCORE\s+ULTRA\s*9\b|\bULTRA\s*9\b", "Intel Core Ultra 9"),
        (r"\bCORE\s+ULTRA\s*7\b|\bULTRA\s*7\b", "Intel Core Ultra 7"),
        (r"\bCORE\s+ULTRA\s*5\b|\bULTRA\s*5\b", "Intel Core Ultra 5"),
        (r"\bI9[-\s]|\bCORE\s*I9\b", "Intel Core i9"),
        (r"\bI7[-\s]|\bCORE\s*I7\b", "Intel Core i7"),
        (r"\bI5[-\s]|\bCORE\s*I5\b", "Intel Core i5"),
        (r"\bI3[-\s]|\bCORE\s*I3\b", "Intel Core i3"),
        (r"\bRYZEN\s*(?:AI\s*)?9\b|\bR9[-\s]", "AMD Ryzen 9"),
        (r"\bRYZEN\s*(?:AI\s*)?7\b|\bR7[-\s]", "AMD Ryzen 7"),
        (r"\bRYZEN\s*(?:AI\s*)?5\b|\bR5[-\s]", "AMD Ryzen 5"),
        (r"\bRYZEN\s*(?:AI\s*)?3\b|\bR3[-\s]", "AMD Ryzen 3"),
        (r"\bAPPLE\s*M5\b|\bM5 CHIP\b", "Apple M5"),
        (r"\bAPPLE\s*M4\b|\bM4 CHIP\b", "Apple M4"),
        (r"\bAPPLE\s*M3\b|\bM3 CHIP\b", "Apple M3"),
        (r"\bAPPLE\s*M2\b|\bM2 CHIP\b", "Apple M2"),
        (r"\bAPPLE\s*M1\b|\bM1 CHIP\b", "Apple M1"),
    ]
    for pat, label in cpu_patterns:
        if re.search(pat, t): cpu = label; break

    ram = "Otro / No especificado"
    for n in [64, 48, 32, 24, 16, 12, 8, 4]:
        if re.search(rf"\b{n}\s*GB\b", t): ram = f"{n} GB"; break

    storage = "Otro / No especificado"
    if re.search(r"\b2\s*TB\b|\b2000\s*GB\b", t): storage = "2 TB SSD"
    elif re.search(r"\b1\s*TB\b|\b1000\s*GB\b|\b1024\s*GB\b", t): storage = "1 TB SSD"
    elif re.search(r"\b512\s*GB\b", t): storage = "512 GB SSD"
    elif re.search(r"\b256\s*GB\b", t): storage = "256 GB SSD"
    elif re.search(r"\b128\s*GB\b", t): storage = "128 GB"

    screen = "Otro / No especificado"
    m = re.search(r"\b(1[0-9]|2[0-9])(?:\.\d)?\s*(?:\"|INCH|IN)\b", t)
    if m: screen = m.group(0).replace("INCH", '"').replace("IN", '"')
    return pd.Series([cpu, ram, storage, screen])


# ============================================================
# PROVIDER DETECTION
# ============================================================
def detect_provider(filename: str) -> str:
    n = os.path.splitext(filename)[0].upper()
    if "HAIFA" in n: return "HAIFA"
    if "ALL PLUS" in n: return "ALL PLUS"
    if "ALLBRAND" in n: return "ALLBRANDS"
    if "AQUA" in n and ("LATOP" in n or "LAPTOP" in n): return "AQUA LAPTOPS"
    if "AQUA" in n: return "AQUA CONSUMER"
    if re.search(r"\bASE\b", n): return "ASE"
    if "CELLU" in n: return "CELLUTECH"
    if "EMOLO" in n: return "EMOLO"
    if "H&Z" in n or "H Z" in n: return "H&Z"
    if "INFLUENTIAL" in n: return "INFLUENTIAL"
    if "PRT" in n: return "PRT"
    if "SNK" in n: return "SNK"
    if "SUNRISE" in n or re.search(r"\bSUN\b", n): return "SUNRISE"
    if "TECH SUPPLIER" in n: return "TECH SUPPLIER"
    if "203_TRADING" in n or "203 TRADING" in n: return "203_TRADING"
    if "TRADING" in n: return "UNLIMITED"
    if "WORLDWIDE" in n: return "WORLDWIDE"
    return re.sub(r"\(\d+\)$", "", n).strip()


# ============================================================
# PARSERS
# ============================================================
def parse_simple_table(xls, provider, sheet, hdr=None, aliases=None) -> pd.DataFrame:
    raw = pd.read_excel(xls, sheet_name=sheet, header=None)
    h = hdr if hdr is not None else header_row(raw)
    if h is None: return empty_frame()
    df = pd.read_excel(xls, sheet_name=sheet, header=h)
    aliases = aliases or {}
    c_sku = first_col(df, aliases.get("sku", ["SKU", "MODEL", "MPN", "PART NUMBER", "PART #", "ITEM", "ITEM NUMBER", "ITEM CODE"]))
    c_desc = first_col(df, aliases.get("desc", ["DESCRIPTION", "PRODUCT", "PRODUCTS", "ITEM DESCRIPTION", "ITEM NAME", "PRODUCT DESCRIPTION"]))
    c_price = first_col(df, aliases.get("price", ["PRICE", "PRICE (USD)", "COST", "FOB", "FOB $", "CASH", "EXW"]))
    c_qty = first_col(df, aliases.get("qty", ["QTY", "QUANTITY", "STOCK", "IN STOCK", "UNITS"]))
    c_eta = first_col(df, aliases.get("eta", ["ETA"]))
    c_loc = first_col(df, aliases.get("location", ["LOCATION", "EXW"]))
    c_moq = first_col(df, aliases.get("moq", ["MOQ"]))
    if c_price is None: return empty_frame()
    rows = []
    for _, r in df.iterrows():
        desc = safe_text(r[c_desc]) if c_desc else ""
        sku = safe_text(r[c_sku]) if c_sku else ""
        if not desc and sku: desc = sku
        row = make_row(provider, sku, desc, r[c_price],
                       stock=r[c_qty] if c_qty else None,
                       moq=r[c_moq] if c_moq else None,
                       eta=r[c_eta] if c_eta else "",
                       location=r[c_loc] if c_loc else "")
        if row: rows.append(row)
    return finalize(rows)


def parse_haifa(xls):
    sheet = next((s for s in xls.sheet_names if s.strip().upper() == "FULL LIST"), xls.sheet_names[0])
    return parse_simple_table(xls, "HAIFA", sheet)


def parse_allplus(xls):
    return parse_simple_table(xls, "ALL PLUS", xls.sheet_names[0], aliases={"sku":["MODEL"], "desc":["DESCRIPTION"], "price":["PRICE"]})


def parse_allbrands(xls):
    raw = pd.read_excel(xls, sheet_name=xls.sheet_names[0], header=None)
    h = header_row(raw)
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], header=h)
    c_desc, c_stock, c_price = first_col(df,["DESCRIPTION"]), first_col(df,["STOCK"]), first_col(df,["PRICE"])
    rows=[]
    for _,r in df.iterrows():
        desc=safe_text(r[c_desc]) if c_desc else ""
        sku,source=infer_sku_from_description(desc,"ALLBRANDS")
        row=make_row("ALLBRANDS",sku,desc,r[c_price] if c_price else None,stock=r[c_stock] if c_stock else None,sku_source=source)
        if row: rows.append(row)
    return finalize(rows)


def parse_aqua(xls, provider):
    raw=pd.read_excel(xls,sheet_name="Sheet1",header=None)
    h=header_row(raw)
    df=pd.read_excel(xls,sheet_name="Sheet1",header=h)
    c_sku=first_col(df,["PART NUMBER"]); c_desc=first_col(df,["DESCRIPTION"]); c_price=first_col(df,["FOB $","FOB"])
    c_mia=first_col(df,["MIAMI"]); c_ny=first_col(df,["NEW YORK"])
    rows=[]
    for _,r in df.iterrows():
        mia=clean_qty(r[c_mia]) if c_mia else None; ny=clean_qty(r[c_ny]) if c_ny else None
        stock=(mia or 0)+(ny or 0) if (mia is not None or ny is not None) else None
        loc=[]
        if mia: loc.append(f"Miami {int(mia)}")
        if ny: loc.append(f"NY {int(ny)}")
        row=make_row(provider,r[c_sku] if c_sku else "",r[c_desc] if c_desc else "",r[c_price] if c_price else None,
                     stock=stock,stock_miami=mia,stock_ny=ny,location=" / ".join(loc))
        if row: rows.append(row)
    return finalize(rows)


def parse_ase(xls):
    raw=pd.read_excel(xls,sheet_name=xls.sheet_names[0],header=None)
    rows=[]
    # ASE repeats the same header for sections. Detect data rows by price in col 3.
    for _,r in raw.iterrows():
        vals=r.tolist()
        # ASE places Model/Description/Price at columns 3/4/5 and repeats headers by section.
        sku=safe_text(vals[3] if len(vals)>3 else "")
        desc=safe_text(vals[4] if len(vals)>4 else "")
        price=clean_price(vals[5] if len(vals)>5 else None)
        if not desc or price is None or sku.upper() in {"MODEL","LOC"}: continue
        if not sku:
            sku,source=infer_sku_from_description(desc,"ASE")
        else:
            source="FILE"
        stock=vals[6] if len(vals)>6 else None
        transit=vals[7] if len(vals)>7 else None
        eta=vals[8] if len(vals)>8 else ""
        row=make_row("ASE",sku,desc,price,stock=stock,transit=transit,eta=eta,sku_source=source)
        if row: rows.append(row)
    return finalize(rows)


def parse_emolo(xls):
    return parse_simple_table(xls,"EMOLO",xls.sheet_names[0],aliases={"sku":["MODEL"],"desc":["DESCRIPTION"],"qty":["QTY"],"price":["PRICE"]})


def parse_hz(xls):
    sheet=next((s for s in xls.sheet_names if s.strip().upper()=="ALL PRODUCTS"),xls.sheet_names[0])
    # Model Number is the more useful cross-vendor MPN. Fall back to SKU/UPC.
    df=pd.read_excel(xls,sheet_name=sheet,header=0)
    rows=[]
    for _,r in df.iterrows():
        sku=safe_text(r.get("Model Number")) or safe_text(r.get("SKU"))
        row=make_row("H&Z",sku,r.get("Description"),r.get("Price (USD)"),stock=r.get("Qty"),moq=r.get("MOQ"),eta=r.get("ETA"),location=r.get("EXW"))
        if row: rows.append(row)
    return finalize(rows)


def parse_influential(xls):
    df=pd.read_excel(xls,sheet_name=xls.sheet_names[0],header=0)
    rows=[]
    for _,r in df.iterrows():
        sku=safe_text(r.get("MPN")) or safe_text(r.get("SKU")) or safe_text(r.get("UPC"))
        row=make_row("INFLUENTIAL",sku,r.get("Description"),r.get("Price"),stock=r.get("Qty"))
        if row: rows.append(row)
    return finalize(rows)


def parse_prt(xls):
    return parse_simple_table(xls,"PRT",xls.sheet_names[0],hdr=0,aliases={"sku":["PART NUMBER"],"desc":["DESCRIPTION"],"qty":["QTY"],"price":["PRICE"]})


def parse_snk(xls):
    rows=[]
    for sheet in xls.sheet_names:
        su=sheet.strip().upper()
        if "IPHONE" in su:  # layout is a matrix, not a normal SKU table; skip safely for now
            continue
        raw=pd.read_excel(xls,sheet_name=sheet,header=None)
        h=header_row(raw)
        if h is None: continue
        df=pd.read_excel(xls,sheet_name=sheet,header=h)
        c_sku=first_col(df,["MODEL","SKU"])
        c_desc=first_col(df,["ALL PRODUCTS","PRODUCTS","DESCRIPTION"])
        c_price=first_col(df,["PRICE (USD$)","EXW - NY","PRICE"])
        c_qty=first_col(df,["UNITS","UNITS - MIAMI","QTY"])
        c_ny=first_col(df,["UNITS - NY"])
        c_mia=first_col(df,["UNITS - MIAMI"])
        c_loc=first_col(df,["LOCATION"])
        if c_price is None: continue
        for _,r in df.iterrows():
            desc=safe_text(r[c_desc]) if c_desc else ""
            sku=safe_text(r[c_sku]) if c_sku else ""
            if not sku or not desc: continue
            mia=clean_qty(r[c_mia]) if c_mia else (clean_qty(r[c_qty]) if c_qty and "MIAMI" in su else None)
            ny=clean_qty(r[c_ny]) if c_ny else (clean_qty(r[c_qty]) if c_qty and "NY STOCK" in su else None)
            stock=clean_qty(r[c_qty]) if c_qty else None
            if c_mia or c_ny: stock=(mia or 0)+(ny or 0)
            loc=safe_text(r[c_loc]) if c_loc else sheet.strip()
            row=make_row("SNK",sku,desc,r[c_price],stock=stock,stock_miami=mia,stock_ny=ny,location=loc)
            if row: rows.append(row)
    return finalize(rows)


def parse_sunrise(xls):
    sheet=next((s for s in xls.sheet_names if "PRICE" in s.upper()),xls.sheet_names[0])
    raw=pd.read_excel(xls,sheet_name=sheet,header=None)
    rows=[]
    # Columns in this workbook: QTY, category, description, stock/transit, Cash, take-all.
    for _,r in raw.iterrows():
        vals=r.tolist()
        if len(vals)<5: continue
        qty=clean_qty(vals[0]); desc=safe_text(vals[2] if len(vals)>2 else "")
        status=safe_text(vals[3] if len(vals)>3 else "").upper()
        cash=clean_price(vals[4] if len(vals)>4 else None)
        if not desc or cash is None or qty is None: continue
        sku,source=infer_sku_from_description(desc,"SUNRISE")
        stock=qty if "STOCK" in status else 0
        transit=qty if "TRANSIT" in status else 0
        row=make_row("SUNRISE",sku,desc,cash,stock=stock,transit=transit,location=status,sku_source=source)
        if row: rows.append(row)
    return finalize(rows)


def parse_tech(xls):
    # Consolidate duplicate item/location rows into one row per SKU at same price.
    df=parse_simple_table(xls,"TECH SUPPLIER",xls.sheet_names[0],hdr=0,
                          aliases={"sku":["ITEM NUMBER"],"desc":["ITEM DESCRIPTION"],"qty":["QUANTITY"],"price":["PRICE"],"location":["LOCATION"]})
    if df.empty: return df
    # Convert rows tagged in transit to En_Transito; Miami rows remain Stock.
    transit_mask=df["Ubicacion"].astype("string").str.upper().str.contains("TRANSIT",na=False)
    df["Stock"] = pd.to_numeric(df["Stock"], errors="coerce").astype("Float64")
    df["En_Transito"] = pd.to_numeric(df["En_Transito"], errors="coerce").astype("Float64")
    if bool(transit_mask.any()):
        df.loc[transit_mask,"En_Transito"] = df.loc[transit_mask,"Stock"].to_numpy()
        df.loc[transit_mask,"Stock"] = 0.0
    grouped=[]
    for (sku,price),g in df.groupby(["SKU","Precio"],dropna=False):
        best=g.iloc[0].copy()
        best["Stock"]=g["Stock"].fillna(0).sum()
        best["En_Transito"]=g["En_Transito"].fillna(0).sum()
        best["Ubicacion"]=" / ".join(sorted(set(x for x in g["Ubicacion"].astype(str) if x and x.lower()!="nan")))
        best["Descripcion"]=max(g["Descripcion"].astype(str),key=len)
        grouped.append(best.to_dict())
    return finalize(grouped)


def parse_unlimited(xls):
    rows=[]
    for sheet in xls.sheet_names:
        raw=pd.read_excel(xls,sheet_name=sheet,header=None)
        h=header_row(raw)
        if h is None: continue
        df=pd.read_excel(xls,sheet_name=sheet,header=h)
        su=sheet.strip().upper()
        # aliases vary by brand sheet
        c_sku=first_col(df,["SKU","ITEM NUMBER","ITEMKEY","ITEM CODE","MODEL"])
        c_desc=first_col(df,["DESCRIPTION","PRODUCTS:","PRODUCT DESCRIPTION","ITEMNAME","KEY FEATURE DESCRIPTION","HP"])
        c_qty=first_col(df,["QUANTITY","MASTER","QTY","AVAILABILITY"])
        c_price=first_col(df,["PROMO PRICE","PRICE","PRICE ","COST"])
        if c_price is None: continue
        # House of Marley has continuation rows for color variants; carry description down.
        if c_desc is not None and "HOUSE OF MARLEY" in su:
            df[c_desc]=df[c_desc].ffill()
        for _,r in df.iterrows():
            sku=safe_text(r[c_sku]) if c_sku else ""
            desc=safe_text(r[c_desc]) if c_desc else ""
            if not sku and desc:
                sku,source=infer_sku_from_description(desc,"UNLIMITED")
            else:
                source="FILE"
            price=r[c_price]
            # If PROMO PRICE exists but is blank, fall back to regular PRICE.
            if clean_price(price) is None and _norm_col(c_price)=="PROMO PRICE":
                regular=first_col(df,["PRICE"])
                price=r[regular] if regular else price
            stock=r[c_qty] if c_qty else None
            # Availability like NOW is not numeric; leave stock unknown.
            row=make_row("UNLIMITED",sku,desc,price,stock=stock,location=sheet.strip(),sku_source=source)
            if row: rows.append(row)
    return finalize(rows)


def parse_203_trading(xls):
    """203 Trading consolidated inventory from the 'Inventory Search' sheet."""
    sheet = "Inventory Search" if "Inventory Search" in xls.sheet_names else xls.sheet_names[0]
    raw = pd.read_excel(xls, sheet_name=sheet, header=None)
    h = None
    for i in range(min(20, len(raw))):
        vals = [_norm_col(v) for v in raw.iloc[i].tolist() if pd.notna(v)]
        if "VENDOR PN" in vals and "PRICE" in vals and any(v in vals for v in ["QTY.", "QTY", "QUANTITY"]):
            h = i
            break
    if h is None:
        return empty_frame()

    df = pd.read_excel(xls, sheet_name=sheet, header=h)
    c_sku = first_col(df, ["VENDOR PN", "SKU", "MPN", "PART NUMBER"])
    c_desc = first_col(df, ["DESCRIPTION", "PRODUCT DESCRIPTION"])
    c_condition = first_col(df, ["CONDITION"])
    c_qty = first_col(df, ["QTY.", "QTY", "QUANTITY"])
    c_price = first_col(df, ["PRICE", "COST"])
    c_form = first_col(df, ["FORM FACTOR", "CATEGORY"])

    rows = []
    if c_price is None:
        return empty_frame()
    for _, r in df.iterrows():
        sku = safe_text(r[c_sku]) if c_sku else ""
        desc = safe_text(r[c_desc]) if c_desc else sku
        condition = safe_text(r[c_condition]) if c_condition else ""
        form = safe_text(r[c_form]) if c_form else ""
        row = make_row(
            "203_TRADING", sku, desc, r[c_price],
            stock=(r[c_qty] if c_qty else None),
            location=form, condition=condition, sku_source="FILE"
        )
        if row:
            rows.append(row)
    return finalize(rows)


def parse_worldwide(xls):
    df=pd.read_excel(xls,sheet_name=xls.sheet_names[0],header=0)
    rows=[]
    for _,r in df.iterrows():
        item=safe_text(r.get("ITEM"))
        sku=item.split(":",1)[1].strip() if ":" in item else item
        row=make_row("WORLDWIDE",sku,r.get("Description"),r.get("FOB"),stock=r.get("QTY"),location="Miami")
        if row: rows.append(row)
    return finalize(rows)


def parse_cellutech(xls):
    # Legacy .xls workbook with several different product families.
    # Requires xlrd when uploaded as .xls.
    parts=[]
    for sheet in xls.sheet_names:
        try:
            su=sheet.strip().upper()
            if su=="TABLETS":
                aliases={"sku":["PART NO"],"desc":["DESCRIPTION"],"qty":["ON HAND"],"price":["FOB DUBAI($)","FOB"]}
            elif su=="HP POLY":
                aliases={"sku":["PART NUMBER"],"desc":["DESCRIPTION"],"price":["PRICE"],"moq":["MOQ"]}
            elif su=="STEEL SERIES":
                aliases={"sku":["PART #"],"desc":["DESCRIPTION"],"qty":["QUANTITY"],"price":["PRICE IN USD","PRICE"]}
            elif su=="DUBAI LAPTOPS":
                aliases={"sku":["PART NO"],"desc":["DESCRIPTION"],"qty":["ON HAND"],"price":["FOB DUBAI($)","FOB"]}
            else:
                aliases=None
            d=parse_simple_table(xls,"CELLUTECH",sheet,hdr=0,aliases=aliases)
            if not d.empty:
                if "DUBAI" in su:
                    d["Ubicacion"]="Dubai"
                parts.append(d)
        except Exception:
            continue
    return pd.concat(parts,ignore_index=True).drop_duplicates() if parts else empty_frame()


PARSERS = {
    "HAIFA": parse_haifa,
    "ALL PLUS": parse_allplus,
    "ALLBRANDS": parse_allbrands,
    "AQUA CONSUMER": lambda x: parse_aqua(x,"AQUA CONSUMER"),
    "AQUA LAPTOPS": lambda x: parse_aqua(x,"AQUA LAPTOPS"),
    "ASE": parse_ase,
    "CELLUTECH": parse_cellutech,
    "EMOLO": parse_emolo,
    "H&Z": parse_hz,
    "INFLUENTIAL": parse_influential,
    "PRT": parse_prt,
    "SNK": parse_snk,
    "SUNRISE": parse_sunrise,
    "TECH SUPPLIER": parse_tech,
    "UNLIMITED": parse_unlimited,
    "203_TRADING": parse_203_trading,
    "WORLDWIDE": parse_worldwide,
}


def parse_uploaded(uploaded) -> Tuple[pd.DataFrame, dict]:
    provider=detect_provider(uploaded.name)
    info={"Archivo":uploaded.name,"Proveedor":provider,"Productos":0,"Estado":"OK","Detalle":""}
    try:
        xls=excel_file(uploaded)
        parser=PARSERS.get(provider)
        if parser is None:
            # Last-resort generic parser across sheets.
            parts=[]
            for s in xls.sheet_names:
                d=parse_simple_table(xls,provider,s)
                if not d.empty: parts.append(d)
            df=pd.concat(parts,ignore_index=True).drop_duplicates() if parts else empty_frame()
        else:
            df=parser(xls)
        info["Productos"]=len(df)
        if df.empty:
            info["Estado"]="⚠️ Sin datos"
            info["Detalle"]="No se detectaron filas válidas con SKU/Descripción y precio."
        return df,info
    except Exception as e:
        info["Estado"]="❌ Error"
        info["Detalle"]=str(e)
        return empty_frame(),info


# ============================================================
# PRICE LIST MANAGER — MVP 3
# Persistencia + historial + publicación
# ============================================================
import sqlite3

SUPPLIER_MASTER_ALIASES = {
    "H&Z": "H&Z", "SUNRISE": "SUNRISE INTERNATIONAL", "ALL PLUS": "ALLPLUS",
    "HAIFA": "HAIFA", "ALLBRANDS": "ALLBRANDS", "AQUA CONSUMER": "AQUA",
    "AQUA LAPTOPS": "AQUA", "SNK": "SNK DISTRIBUTION INC", "WORLDWIDE": "WORLWIDE",
    "TECH SUPPLIER": "TECH SUPPLIER", "UNLIMITED": "TRADING UNLIMITED",
    "203_TRADING": "203 TRADING", "EMOLO": "EMOLO", "PRT": "PRT",
}

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "motech_pricelist.db"


def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS product_overrides (
            product_key TEXT PRIMARY KEY,
            manual_price REAL,
            manual_margin REAL,
            hidden INTEGER NOT NULL DEFAULT 0,
            category_override TEXT,
            subcategory_override TEXT,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS manual_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_item TEXT NOT NULL,
            supplier_name TEXT NOT NULL DEFAULT 'MANUAL',
            supplier_code TEXT,
            brand TEXT,
            category TEXT,
            subcategory TEXT,
            description TEXT NOT NULL,
            condition TEXT NOT NULL DEFAULT 'NEW',
            processor TEXT,
            ram TEXT,
            storage TEXT,
            screen TEXT,
            stock REAL NOT NULL,
            cost REAL NOT NULL,
            moq REAL,
            eta TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS review_actions (
            issue_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            note TEXT,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS publication_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            published_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS publication_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            product_key TEXT NOT NULL,
            item_publico TEXT,
            supplier TEXT,
            cost REAL,
            published_price REAL,
            stock_real REAL,
            stock_publico TEXT,
            moq TEXT,
            eta TEXT,
            category TEXT,
            subcategory TEXT,
            description TEXT,
            condition TEXT,
            hot_deal INTEGER NOT NULL DEFAULT 0,
            new_arrival INTEGER NOT NULL DEFAULT 0,
            low_stock INTEGER NOT NULL DEFAULT 0,
            hidden INTEGER NOT NULL DEFAULT 0,
            published_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pub_items_run ON publication_items(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pub_items_product ON publication_items(product_key,published_at)")
        conn.commit()


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load_overrides():
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM product_overrides").fetchall()
    return {r["product_key"]: dict(r) for r in rows}


def save_override(product_key, manual_price, manual_margin, hidden, category_override=None, subcategory_override=None):
    with db_conn() as conn:
        conn.execute("""INSERT INTO product_overrides
            (product_key,manual_price,manual_margin,hidden,category_override,subcategory_override,updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(product_key) DO UPDATE SET
                manual_price=excluded.manual_price,
                manual_margin=excluded.manual_margin,
                hidden=excluded.hidden,
                category_override=excluded.category_override,
                subcategory_override=excluded.subcategory_override,
                updated_at=excluded.updated_at
        """, (product_key, manual_price, manual_margin, int(bool(hidden)), category_override, subcategory_override, now_iso()))
        conn.commit()


def load_manual_products():
    with db_conn() as conn:
        rows=conn.execute("SELECT * FROM manual_products WHERE active=1 ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def add_manual_product(data):
    with db_conn() as conn:
        conn.execute("""INSERT INTO manual_products
            (base_item,supplier_name,supplier_code,brand,category,subcategory,description,condition,
             processor,ram,storage,screen,stock,cost,moq,eta,active,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""", (
            data["base_item"], data.get("supplier_name") or "MANUAL", data.get("supplier_code") or "MAN",
            data.get("brand"), data.get("category"), data.get("subcategory"), data["description"], data.get("condition") or "NEW",
            data.get("processor"), data.get("ram"), data.get("storage"), data.get("screen"), data["stock"], data["cost"],
            data.get("moq"), data.get("eta"), now_iso(), now_iso()
        ))
        conn.commit()


def deactivate_manual_product(row_id):
    with db_conn() as conn:
        conn.execute("UPDATE manual_products SET active=0, updated_at=? WHERE id=?", (now_iso(), int(row_id)))
        conn.commit()


def review_status(issue_key):
    with db_conn() as conn:
        r=conn.execute("SELECT status FROM review_actions WHERE issue_key=?",(issue_key,)).fetchone()
    return r["status"] if r else None


def save_review_action(issue_key,status,note=""):
    with db_conn() as conn:
        conn.execute("""INSERT INTO review_actions(issue_key,status,note,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(issue_key) DO UPDATE SET status=excluded.status,note=excluded.note,updated_at=excluded.updated_at""",
            (issue_key,status,note,now_iso()))
        conn.commit()


def latest_publication_run():
    with db_conn() as conn:
        r=conn.execute("SELECT id,published_at FROM publication_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def latest_publication_items():
    run=latest_publication_run()
    if not run:
        return pd.DataFrame()
    with db_conn() as conn:
        rows=conn.execute("SELECT * FROM publication_items WHERE run_id=? ORDER BY id",(run["id"],)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def product_history(product_key, days=7):
    cutoff=(datetime.datetime.now()-datetime.timedelta(days=days)).isoformat(timespec="seconds")
    with db_conn() as conn:
        rows=conn.execute("""SELECT pi.* FROM publication_items pi
            WHERE pi.product_key=? AND pi.published_at>=? ORDER BY pi.published_at DESC""",
            (product_key,cutoff)).fetchall()
    return [dict(r) for r in rows]


def prune_publication_history(days=7):
    cutoff=(datetime.datetime.now()-datetime.timedelta(days=days)).isoformat(timespec="seconds")
    with db_conn() as conn:
        old=conn.execute("SELECT id FROM publication_runs WHERE published_at<?",(cutoff,)).fetchall()
        ids=[r["id"] for r in old]
        if ids:
            marks=",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM publication_items WHERE run_id IN ({marks})",ids)
            conn.execute(f"DELETE FROM publication_runs WHERE id IN ({marks})",ids)
        conn.commit()


def publish_snapshot(df):
    ts=now_iso()
    with db_conn() as conn:
        cur=conn.execute("INSERT INTO publication_runs(published_at) VALUES(?)",(ts,))
        run_id=cur.lastrowid
        for _,r in df.iterrows():
            if bool(r.get("Oculto",False)):
                continue
            conn.execute("""INSERT INTO publication_items
                (run_id,product_key,item_publico,supplier,cost,published_price,stock_real,stock_publico,moq,eta,category,subcategory,description,condition,hot_deal,new_arrival,low_stock,hidden,published_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                run_id,safe_text(r.get("PRODUCT_KEY")),safe_text(r.get("ITEM_PUBLICO")),safe_text(r.get("Proveedor")),
                float(r.get("Costo")) if pd.notna(r.get("Costo")) else None,
                float(r.get("Precio_Publicado")) if pd.notna(r.get("Precio_Publicado")) else None,
                float(r.get("Stock_Real")) if pd.notna(r.get("Stock_Real")) else None,safe_text(r.get("Stock_Publico")),
                safe_text(r.get("MOQ_Final")),safe_text(r.get("ETA_Final")),safe_text(r.get("Categoria")),safe_text(r.get("Subcategoria_Manual")),
                safe_text(r.get("Descripcion")),safe_text(r.get("Condicion_Normalizada")),int(bool(r.get("HOT_DEAL",False))),
                int(bool(r.get("NEW_ARRIVAL",False))),int(bool(r.get("LOW_STOCK",False))),0,ts))
        conn.commit()
    prune_publication_history(7)
    return run_id,ts


init_db()


def _clean_master_name(v):
    return re.sub(r"\s+", " ", safe_text(v).strip()).upper()


def load_supplier_master():
    candidates=[APP_DIR/"supplier_master.xlsx",Path.cwd()/"supplier_master.xlsx"]
    p=next((x for x in candidates if x.exists()),None)
    if p is None:
        return pd.DataFrame(columns=["CODIGO PROVEEDOR","MOQ","ETA","NOMBRE","_NOMBRE_N"])
    try:
        df=pd.read_excel(p)
        rename={}
        for c in df.columns:
            n=_norm_col(c)
            if "CODIGO" in n and "PROVEEDOR" in n: rename[c]="CODIGO PROVEEDOR"
            elif n=="MOQ": rename[c]="MOQ"
            elif n=="ETA": rename[c]="ETA"
            elif n in {"NOMBRE","PROVEEDOR","SUPPLIER"}: rename[c]="NOMBRE"
        df=df.rename(columns=rename)
        for c in ["CODIGO PROVEEDOR","MOQ","ETA","NOMBRE"]:
            if c not in df.columns: df[c]=pd.NA
        df["_NOMBRE_N"]=df["NOMBRE"].map(_clean_master_name)
        return df[["CODIGO PROVEEDOR","MOQ","ETA","NOMBRE","_NOMBRE_N"]]
    except Exception:
        return pd.DataFrame(columns=["CODIGO PROVEEDOR","MOQ","ETA","NOMBRE","_NOMBRE_N"])


def supplier_defaults(provider,master):
    target=SUPPLIER_MASTER_ALIASES.get(provider,provider)
    if master.empty: return "",None,None
    hit=master[master["_NOMBRE_N"]==_clean_master_name(target)]
    if hit.empty: return "",None,None
    r=hit.iloc[0]
    return safe_text(r.get("CODIGO PROVEEDOR")),clean_qty(r.get("MOQ")),clean_qty(r.get("ETA"))


def normalize_category_name(v):
    s=re.sub(r"^[^A-Za-z0-9]+","",safe_text(v)).strip()
    return s.upper() if s else "OTHER"


def base_item(sku):
    return re.sub(r"_[A-Z0-9]{2,6}$","",safe_text(sku).upper().strip())


def public_stock(stock):
    q=clean_qty(stock)
    if q is None or q<=0: return ""
    if q>100: return "100+"
    if q>20: return "20+"
    return str(int(q)) if float(q).is_integer() else str(q)


def default_margin_pct(category, cost):
    cat=safe_text(category).upper()
    if "LAPTOP" in cat or "NOTEBOOK" in cat or "DESKTOP" in cat:
        return 2.0
    return None


def manual_products_frame():
    rows=[]
    for m in load_manual_products():
        rows.append({
            "Proveedor": safe_text(m.get("supplier_name")) or "MANUAL",
            "SKU": safe_text(m.get("base_item")).upper(),
            "SKU_Fuente": "MANUAL",
            "Descripcion": safe_text(m.get("description")),
            "Condicion": safe_text(m.get("condition")) or "NEW",
            "Precio": float(m.get("cost")),
            "Stock": float(m.get("stock")),
            "Stock_Miami": pd.NA,
            "Stock_NY": pd.NA,
            "En_Transito": 0,
            "MOQ": m.get("moq"),
            "ETA": safe_text(m.get("eta")),
            "Ubicacion": "MANUAL",
            "_MANUAL_ID": m.get("id"),
            "_MANUAL_CODE": safe_text(m.get("supplier_code")) or "MAN",
            "_MANUAL_CATEGORY": safe_text(m.get("category")),
            "_MANUAL_SUBCATEGORY": safe_text(m.get("subcategory")),
            "_MANUAL_PROCESSOR": safe_text(m.get("processor")),
            "_MANUAL_RAM": safe_text(m.get("ram")),
            "_MANUAL_STORAGE": safe_text(m.get("storage")),
            "_MANUAL_SCREEN": safe_text(m.get("screen")),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def prepare_offers(df_all,master):
    df=df_all.copy()
    df["Categoria"]=df.apply(lambda r:normalize_category_name(clasificar_categoria(r["Descripcion"],r["SKU"],r.get("Condicion",""))),axis=1)
    specs=df.apply(lambda r:extraer_especificaciones(f'{r["Descripcion"]} {r["SKU"]}'),axis=1)
    specs.columns=["Procesador","RAM","Almacenamiento","Pantalla"]
    df[["Procesador","RAM","Almacenamiento","Pantalla"]]=specs

    if "_MANUAL_CATEGORY" in df.columns:
        mask=df["_MANUAL_CATEGORY"].fillna("").astype(str).str.strip().ne("")
        df.loc[mask,"Categoria"]=df.loc[mask,"_MANUAL_CATEGORY"].map(normalize_category_name)
        for target,src in [("Procesador","_MANUAL_PROCESSOR"),("RAM","_MANUAL_RAM"),("Almacenamiento","_MANUAL_STORAGE"),("Pantalla","_MANUAL_SCREEN")]:
            if src in df.columns:
                m=df[src].fillna("").astype(str).str.strip().ne("")
                df.loc[m,target]=df.loc[m,src]

    df["ITEM_BASE"]=df["SKU"].map(base_item)
    codes=[]; moqs=[]; etas=[]; full=[]
    for _,r in df.iterrows():
        if safe_text(r.get("SKU_Fuente")).upper()=="MANUAL":
            code=safe_text(r.get("_MANUAL_CODE")) or "MAN"; dm=de=None
        else:
            code,dm,de=supplier_defaults(r["Proveedor"],master)
        rm=clean_qty(r.get("MOQ")); re_=safe_text(r.get("ETA"))
        m=rm if rm is not None else dm
        e=re_ if re_ else (int(de) if de is not None else "")
        codes.append(code); moqs.append(m); etas.append(e)
        full.append(f'{base_item(r["SKU"])}_{code}' if code else base_item(r["SKU"]))
    df["Codigo_Proveedor"]=codes; df["MOQ_Final"]=moqs; df["ETA_Final"]=etas; df["ITEM_PUBLICO"]=full
    df["Stock_Real"]=pd.to_numeric(df["Stock"],errors="coerce")
    df["Costo"]=pd.to_numeric(df["Precio"],errors="coerce")
    df["Condicion_Normalizada"]=df["Condicion"].fillna("").astype(str).str.upper().str.strip().replace({"":"NEW"})
    df["Elegible_Stock"]=df["Stock_Real"].fillna(0)>20
    moq_num=pd.to_numeric(df["MOQ_Final"],errors="coerce")
    df["Elegible_MOQ"]=moq_num.isna()|(moq_num<=df["Stock_Real"].fillna(0))
    df["Elegible"]=df["Elegible_Stock"]&df["Elegible_MOQ"]&df["Costo"].notna()
    key_cols=["ITEM_BASE","Condicion_Normalizada","Procesador","RAM","Almacenamiento","Pantalla"]
    for c in key_cols: df[c]=df[c].fillna("").astype(str).str.upper().str.strip()
    df["PRODUCT_KEY"]=df[key_cols].agg("|".join,axis=1)
    return df


def _provider_promo_flag(row):
    text=(safe_text(row.get("Descripcion"))+" "+safe_text(row.get("Ubicacion"))).upper()
    return ("HOT DEAL" in text) or ("PRICE DROP" in text) or ("PROMO" in text and "PRICE" in text)


def select_winners(offers, overrides):
    eligible=offers[offers["Elegible"]].copy()
    latest=latest_publication_items()
    prev_map={} if latest.empty else {r["product_key"]:r for _,r in latest.iterrows()}
    winners=[]; alternatives={}
    for key,g in eligible.groupby("PRODUCT_KEY",dropna=False):
        ordered=g.sort_values(["Costo","Stock_Real"],ascending=[True,False]).reset_index(drop=True)
        if ordered.empty: continue
        w=ordered.iloc[0].copy()
        w["Stock_Publico"]=public_stock(w["Stock_Real"])
        w["Alternativas"]=max(len(ordered)-1,0)
        ov=overrides.get(key,{})
        margin=ov.get("manual_margin")
        if margin is None: margin=default_margin_pct(w.get("Categoria"),w.get("Costo"))
        w["Margen_Pct"]=margin
        suggested=(float(w["Costo"])*(1+float(margin)/100)) if margin is not None and pd.notna(w["Costo"]) else None
        w["Precio_Sugerido"]=suggested
        manual=ov.get("manual_price")
        w["Precio_Publicado"]=float(manual) if manual is not None else suggested
        w["Precio_Manual"]=manual is not None
        w["Oculto"]=bool(ov.get("hidden",0))
        if safe_text(ov.get("category_override")): w["Categoria"]=normalize_category_name(ov.get("category_override"))
        w["Subcategoria_Manual"]=safe_text(ov.get("subcategory_override"))
        prev=prev_map.get(key)
        w["Costo_Anterior"]=float(prev["cost"]) if prev is not None and pd.notna(prev.get("cost")) else pd.NA
        if prev is not None and pd.notna(prev.get("cost")) and float(prev.get("cost"))!=0:
            w["Variacion_Costo_Pct"]=(float(w["Costo"])-float(prev["cost"]))/float(prev["cost"])*100
        else:
            w["Variacion_Costo_Pct"]=pd.NA
        # Nuevo si no estaba en la última publicación. La etiqueta dura 3 días desde su primera publicación.
        hist=product_history(key,7)
        if not hist:
            new_arrival=True
        else:
            first=min(datetime.datetime.fromisoformat(h["published_at"]) for h in hist if h.get("published_at"))
            new_arrival=(datetime.datetime.now()-first).days < 3
        w["NEW_ARRIVAL"]=bool(new_arrival)
        # HOT DEAL por señal explícita del proveedor. La caída histórica se muestra aparte y >25% exige revisión.
        w["HOT_DEAL"]=bool(_provider_promo_flag(w))
        w["LOW_STOCK"]=False
        winners.append(w.to_dict()); alternatives[key]=ordered

    # Productos ya publicados que hoy no tienen oferta >20: permitir LOW STOCK hasta 2 días; día 3 se retira.
    existing_keys={x["PRODUCT_KEY"] for x in winners}
    if not latest.empty:
        for _,prev in latest.iterrows():
            key=safe_text(prev.get("product_key"))
            if not key or key in existing_keys:
                continue
            current=offers[offers["PRODUCT_KEY"]==key].copy()
            current=current[(current["Costo"].notna()) & (current["Stock_Real"].fillna(0)>0) & (current["Stock_Real"].fillna(0)<=20)]
            if current.empty:
                continue
            current=current.sort_values(["Costo","Stock_Real"],ascending=[True,False]).reset_index(drop=True)
            c=current.iloc[0].copy()
            # Cuenta publicaciones consecutivas previas marcadas LOW STOCK, máximo 2 publicaciones antes de retirar.
            hist=product_history(key,7)
            consecutive=0
            for h in hist:
                if int(h.get("low_stock") or 0)==1: consecutive+=1
                else: break
            if consecutive>=2:
                continue
            c["Stock_Publico"]=public_stock(c["Stock_Real"])
            c["Alternativas"]=max(len(current)-1,0)
            ov=overrides.get(key,{})
            margin=ov.get("manual_margin")
            if margin is None: margin=default_margin_pct(c.get("Categoria"),c.get("Costo"))
            c["Margen_Pct"]=margin
            suggested=(float(c["Costo"])*(1+float(margin)/100)) if margin is not None and pd.notna(c["Costo"]) else None
            c["Precio_Sugerido"]=suggested
            manual=ov.get("manual_price")
            c["Precio_Publicado"]=float(manual) if manual is not None else suggested
            c["Precio_Manual"]=manual is not None
            c["Oculto"]=bool(ov.get("hidden",0))
            if safe_text(ov.get("category_override")): c["Categoria"]=normalize_category_name(ov.get("category_override"))
            c["Subcategoria_Manual"]=safe_text(ov.get("subcategory_override"))
            c["Costo_Anterior"]=float(prev["cost"]) if pd.notna(prev.get("cost")) else pd.NA
            if pd.notna(prev.get("cost")) and float(prev.get("cost"))!=0:
                c["Variacion_Costo_Pct"]=(float(c["Costo"])-float(prev["cost"]))/float(prev["cost"])*100
            else: c["Variacion_Costo_Pct"]=pd.NA
            c["NEW_ARRIVAL"]=False; c["HOT_DEAL"]=bool(_provider_promo_flag(c)); c["LOW_STOCK"]=True
            winners.append(c.to_dict()); alternatives[key]=current

    return pd.DataFrame(winners),alternatives


def build_review_issues(offers, winners, import_log):
    issues=[]
    for _,r in import_log.iterrows():
        if int(r.get("Productos",0) or 0)<=0:
            issues.append({"ISSUE_KEY":f'FILE::{r.get("Archivo")}',"Tipo":"ARCHIVO","Producto":"—","Proveedor":r.get("Proveedor"),
                           "Motivo":"Verificar archivo Excel; no se importaron productos.","Detalle":safe_text(r.get("Detalle"))})
    bad=offers[~offers["Elegible"]].copy()
    for _,r in bad.iterrows():
        blocking=[]
        if not bool(r.get("Elegible_MOQ")): blocking.append("MOQ mayor que stock")
        if pd.isna(r.get("Costo")): blocking.append("Costo inválido")
        if blocking:
            ik=f'OFFER::{r.get("Proveedor")}::{r.get("PRODUCT_KEY")}::{"/".join(blocking)}'
            issues.append({"ISSUE_KEY":ik,"Tipo":"PRODUCTO","Producto":r.get("ITEM_PUBLICO"),"Proveedor":r.get("Proveedor"),
                           "Motivo":"; ".join(blocking),"Detalle":safe_text(r.get("Descripcion"))})
    for _,r in winners.iterrows():
        cat=safe_text(r.get("Categoria")).upper()
        if any(x in cat for x in ["LAPTOP","NOTEBOOK","DESKTOP"]):
            missing=[]
            if not safe_text(r.get("Procesador")): missing.append("procesador")
            if not safe_text(r.get("RAM")): missing.append("RAM")
            if not safe_text(r.get("Almacenamiento")): missing.append("almacenamiento")
            if missing:
                ik=f'ATTR::{r.get("PRODUCT_KEY")}::{",".join(missing)}'
                issues.append({"ISSUE_KEY":ik,"Tipo":"ATRIBUTOS","Producto":r.get("ITEM_PUBLICO"),"Proveedor":r.get("Proveedor"),
                               "Motivo":"Información incompleta: "+", ".join(missing),"Detalle":safe_text(r.get("Descripcion"))})
    # Variación de costo > ±25% respecto a la última publicación: revisión obligatoria.
    for _,r in winners.iterrows():
        v=pd.to_numeric(pd.Series([r.get("Variacion_Costo_Pct")]),errors="coerce").iloc[0]
        if pd.notna(v) and abs(float(v))>25:
            ik=f'PRICEVAR::{r.get("PRODUCT_KEY")}::{round(float(v),2)}'
            issues.append({"ISSUE_KEY":ik,"Tipo":"PRECIO","Producto":r.get("ITEM_PUBLICO"),"Proveedor":r.get("Proveedor"),
                           "Motivo":f'Variación de costo {float(v):+.1f}% (supera ±25%)',
                           "Detalle":f'Costo anterior: {r.get("Costo_Anterior")} · Costo actual: {r.get("Costo")}'})
        if bool(r.get("Precio_Manual")) and pd.notna(v) and abs(float(v))>0.01:
            ik=f'MANPRICE::{r.get("PRODUCT_KEY")}::{round(float(r.get("Costo",0)),2)}'
            issues.append({"ISSUE_KEY":ik,"Tipo":"PRECIO MANUAL","Producto":r.get("ITEM_PUBLICO"),"Proveedor":r.get("Proveedor"),
                           "Motivo":"El costo cambió; revisar precio manual.",
                           "Detalle":f'Variación de costo: {float(v):+.1f}%'})
    pending=[]
    for i in issues:
        status=review_status(i["ISSUE_KEY"])
        if status not in {"APROBADO","IGNORADO"}: pending.append(i)
    return pd.DataFrame(pending)


def render_manual_form(form_key, offers=None):
    with st.form(form_key):
        a,b,c=st.columns(3)
        with a:
            bi=st.text_input("ITEM base *")
            brand=st.text_input("Marca")
            category=st.selectbox("Categoría",["LAPTOPS","DESKTOPS","MONITORS","GAMING","MULTIMEDIA","STORAGE","NETWORKING","ACCESSORIES & OTHERS","REFURBISHED","OTHER"])
            subcat=st.text_input("Subcategoría")
        with b:
            cond=st.selectbox("Condición",["NEW","REFURBISHED","OFF-LEASE"])
            stock=st.number_input("Stock *",min_value=0.0,value=0.0,step=1.0)
            cost=st.number_input("Costo USD *",min_value=0.0,value=0.0,step=1.0)
            moq=st.number_input("MOQ",min_value=0.0,value=1.0,step=1.0)
        with c:
            supplier=st.text_input("Fuente / proveedor manual",value="MANUAL")
            code=st.text_input("Código para sufijo",value="MAN")
            eta=st.text_input("ETA")
            processor=st.text_input("Procesador")
            ram=st.text_input("RAM")
            storage=st.text_input("Almacenamiento")
            screen=st.text_input("Pantalla")
        desc=st.text_area("Modelo y descripción *")
        submitted=st.form_submit_button("Guardar producto manual",type="primary")
        if submitted:
            if not bi.strip() or not desc.strip() or cost<=0 or stock<=0:
                st.error("Completa ITEM, descripción, costo y stock.")
                return
            if offers is not None and not offers.empty:
                existing=offers[offers["ITEM_BASE"].astype(str).str.upper()==bi.strip().upper()]
                if not existing.empty:
                    st.warning(f"Este ITEM ya existe en {existing['Proveedor'].nunique()} fuente(s). Se guardará como una oferta adicional y competirá por mejor costo.")
            add_manual_product({"base_item":bi.strip().upper(),"supplier_name":supplier.strip() or "MANUAL","supplier_code":code.strip().upper() or "MAN",
                "brand":brand,"category":category,"subcategory":subcat,"description":desc,"condition":cond,"processor":processor,"ram":ram,
                "storage":storage,"screen":screen,"stock":stock,"cost":cost,"moq":moq,"eta":eta})
            st.success("Producto manual guardado.")
            st.rerun()


logo_path=next((p for p in [APP_DIR/"logo.png",APP_DIR/"Logo.png",Path.cwd()/"logo.png"] if p.exists()),None)
if logo_path:
    c1,c2=st.columns([0.7,5.3],vertical_alignment="center")
    with c1: st.image(str(logo_path),width=84)
    with c2:
        st.markdown('<div class="main-header">Motech Miami — Price List Manager</div>',unsafe_allow_html=True)
        st.markdown('<div class="sub-header">Panel interno · Historial, alertas y publicación</div>',unsafe_allow_html=True)
else:
    st.markdown('<div class="main-header">Motech Miami — Price List Manager</div>',unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Panel interno · Historial, alertas y publicación</div>',unsafe_allow_html=True)

master=load_supplier_master()
with st.sidebar:
    st.header("Carga diaria")
    uploaded_files=st.file_uploader("Subir listas Excel de proveedores",type=["xlsx","xls"],accept_multiple_files=True)
    if master.empty: st.warning("No se encontró supplier_master.xlsx.")
    else: st.success(f"Maestro de proveedores cargado: {len(master)} registros")
    st.caption("In Transit no se utiliza como stock disponible.")
    st.divider()
    st.caption("MVP 4 · Borrador, historial de 7 días y publicación controlada.")

if not uploaded_files:
    page=st.radio("Sección",["Cargar proveedores","Agregar producto manual"],horizontal=True,label_visibility="collapsed")
    if page=="Cargar proveedores":
        st.info("Sube las listas de proveedores para comenzar la actualización diaria.")
    else:
        st.subheader("Agregar producto manual")
        render_manual_form("manual_empty")
        existing=load_manual_products()
        if existing:
            st.markdown("#### Productos manuales activos")
            st.dataframe(pd.DataFrame(existing)[["id","base_item","description","stock","cost","moq","eta"]],use_container_width=True,hide_index=True,
                         column_config={"cost":st.column_config.NumberColumn(format="$%.2f")})
    st.stop()

frames=[]; logs=[]
for f in uploaded_files:
    d,info=parse_uploaded(f)
    if d.empty:
        info["Estado"]="⚠️ Verificar archivo Excel"
        if not info.get("Detalle"): info["Detalle"]="No se importaron productos de este archivo."
    else:
        frames.append(d)
    logs.append(info)
manual_df=manual_products_frame()
if not manual_df.empty: frames.append(manual_df)

log_df=pd.DataFrame(logs)
if not frames:
    st.error("No hay productos válidos para procesar.")
    st.dataframe(log_df,use_container_width=True,hide_index=True)
    st.stop()

df_all=pd.concat(frames,ignore_index=True,sort=False)
offers=prepare_offers(df_all,master)
overrides=load_overrides()
winners,alternatives=select_winners(offers,overrides)
issues=build_review_issues(offers,winners,log_df)

valid_files=int((log_df["Productos"]>0).sum()) if not log_df.empty else 0
review_count=len(issues)
manual_price_count=int(winners["Precio_Manual"].sum()) if not winners.empty else 0
manual_products_count=len(load_manual_products())
last_pub=latest_publication_run()
last_pub_label=last_pub["published_at"].replace("T"," ") if last_pub else "Nunca"
st.markdown(
    f'<div class="kpi-strip">'
    f'<div class="kpi-box"><div class="kpi-value">{valid_files}</div><div class="kpi-label">Archivos válidos</div></div>'
    f'<div class="kpi-box"><div class="kpi-value">{len(winners):,}</div><div class="kpi-label">Productos seleccionados</div></div>'
    f'<div class="kpi-box"><div class="kpi-value">{review_count}</div><div class="kpi-label">Revisión requerida</div></div>'
    f'<div class="kpi-box"><div class="kpi-value">{manual_products_count}</div><div class="kpi-label">Productos manuales</div></div>'
    f'</div>', unsafe_allow_html=True)

page=st.radio("Sección",["Productos","Revisión requerida","Resumen y publicación","Agregar producto manual","Resultado de importación"],horizontal=True,label_visibility="collapsed")

if page=="Resultado de importación":
    st.subheader("Resultado de importación")
    st.dataframe(log_df,use_container_width=True,hide_index=True)
    st.stop()

if page=="Resumen y publicación":
    st.subheader("Resumen antes de publicar")
    latest=latest_publication_items()
    prev_keys=set(latest["product_key"].astype(str)) if not latest.empty else set()
    curr_visible=winners[~winners["Oculto"]].copy() if not winners.empty else winners.copy()
    curr_keys=set(curr_visible["PRODUCT_KEY"].astype(str)) if not curr_visible.empty else set()
    new_count=len(curr_keys-prev_keys)
    removed_count=len(prev_keys-curr_keys)
    price_changes=0; supplier_changes=0
    if not latest.empty and not curr_visible.empty:
        prev_map={r["product_key"]:r for _,r in latest.iterrows()}
        for _,r in curr_visible.iterrows():
            p=prev_map.get(r["PRODUCT_KEY"])
            if p is None: continue
            if pd.notna(r.get("Precio_Publicado")) and pd.notna(p.get("published_price")) and abs(float(r["Precio_Publicado"])-float(p["published_price"]))>0.005: price_changes+=1
            if safe_text(r.get("Proveedor"))!=safe_text(p.get("supplier")): supplier_changes+=1
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Productos nuevos",new_count)
    c2.metric("Productos retirados",removed_count)
    c3.metric("Cambios de precio",price_changes)
    c4.metric("Cambios de proveedor",supplier_changes)
    c5,c6,c7,c8=st.columns(4)
    c5.metric("HOT DEALS",int(curr_visible["HOT_DEAL"].fillna(False).sum()) if "HOT_DEAL" in curr_visible else 0)
    c6.metric("NEW ARRIVALS",int(curr_visible["NEW_ARRIVAL"].fillna(False).sum()) if "NEW_ARRIVAL" in curr_visible else 0)
    c7.metric("LOW STOCK",int(curr_visible["LOW_STOCK"].fillna(False).sum()) if "LOW_STOCK" in curr_visible else 0)
    c8.metric("Revisión requerida",len(issues))
    st.caption(f"Última publicación: {last_pub_label}")
    if len(issues)>0:
        st.warning("Hay incidencias pendientes. Revísalas antes de publicar la actualización.")
    else:
        st.success("No hay incidencias pendientes de revisión.")
    preview_cols=["ITEM_PUBLICO","Descripcion","Proveedor","Stock_Publico","Costo","Precio_Publicado","HOT_DEAL","NEW_ARRIVAL","LOW_STOCK"]
    preview=curr_visible[[c for c in preview_cols if c in curr_visible.columns]].copy()
    st.dataframe(preview.head(250),use_container_width=True,hide_index=True,column_config={"Costo":st.column_config.NumberColumn(format="$%.2f"),"Precio_Publicado":st.column_config.NumberColumn(format="$%.2f")})
    confirm=st.checkbox("Confirmo que revisé el resumen y deseo reemplazar la versión pública actual.")
    disabled=(len(issues)>0) or (not confirm)
    if st.button("PUBLICAR ACTUALIZACIÓN",type="primary",use_container_width=True,disabled=disabled):
        run_id,ts=publish_snapshot(curr_visible)
        st.success(f"Actualización publicada correctamente. Versión #{run_id} · {ts.replace('T',' ')}")
        st.rerun()
    st.stop()

if page=="Agregar producto manual":
    st.subheader("Agregar producto manual")
    render_manual_form("manual_main",offers)
    existing=load_manual_products()
    if existing:
        st.markdown("#### Productos manuales activos")
        md=pd.DataFrame(existing)
        st.dataframe(md[["id","base_item","supplier_name","description","stock","cost","moq","eta"]],use_container_width=True,hide_index=True,
                     column_config={"cost":st.column_config.NumberColumn(format="$%.2f")})
        choices=[""]+[f'{x["id"]} — {x["base_item"]} — {x["description"][:65]}' for x in existing]
        selected=st.selectbox("Desactivar producto manual",choices)
        if selected and st.button("Desactivar seleccionado"):
            deactivate_manual_product(int(selected.split(" — ",1)[0])); st.rerun()
    st.stop()

if page=="Revisión requerida":
    st.subheader("Revisión requerida")
    if issues.empty:
        st.success("No hay incidencias pendientes de revisión.")
        st.stop()
    st.dataframe(issues[["Tipo","Producto","Proveedor","Motivo","Detalle"]],use_container_width=True,hide_index=True)
    opts={f'{r["Tipo"]} · {r["Producto"]} · {r["Motivo"]}':r["ISSUE_KEY"] for _,r in issues.iterrows()}
    label=st.selectbox("Incidencia",list(opts.keys())); ik=opts[label]
    note=st.text_input("Nota interna")
    c1,c2=st.columns(2)
    with c1:
        if st.button("Marcar como revisado",type="primary",use_container_width=True):
            save_review_action(ik,"APROBADO",note); st.rerun()
    with c2:
        if st.button("Ignorar esta incidencia",use_container_width=True):
            save_review_action(ik,"IGNORADO",note); st.rerun()
    st.stop()

st.subheader("Productos seleccionados")
if winners.empty:
    st.warning("No hay productos elegibles."); st.stop()
search=st.text_input("Buscar",placeholder="ITEM, modelo, descripción, procesador, RAM...")
f1,f2,f3,f4=st.columns(4)
with f1: cat=st.selectbox("Categoría",["TODAS"]+sorted(x for x in winners["Categoria"].dropna().unique().tolist() if x))
with f2: prov=st.selectbox("Proveedor seleccionado",["TODOS"]+sorted(winners["Proveedor"].dropna().unique().tolist()))
with f3: cond=st.selectbox("Condición",["TODAS"]+sorted(winners["Condicion_Normalizada"].dropna().unique().tolist()))
with f4: vis=st.selectbox("Visibilidad",["TODOS","VISIBLES","OCULTOS"])
view=winners.copy()
if cat!="TODAS": view=view[view["Categoria"]==cat]
if prov!="TODOS": view=view[view["Proveedor"]==prov]
if cond!="TODAS": view=view[view["Condicion_Normalizada"]==cond]
if vis=="VISIBLES": view=view[~view["Oculto"]]
elif vis=="OCULTOS": view=view[view["Oculto"]]
if search.strip():
    q=search.strip().upper()
    hay=(view["ITEM_PUBLICO"].astype(str)+" "+view["Descripcion"].astype(str)+" "+view["Procesador"].astype(str)+" "+view["RAM"].astype(str)+" "+view["Almacenamiento"].astype(str)).str.upper()
    view=view[hay.str.contains(re.escape(q),na=False)]
show=view[["Oculto","Categoria","ITEM_PUBLICO","Descripcion","Proveedor","Stock_Real","Stock_Publico","Costo","Costo_Anterior","Variacion_Costo_Pct","Margen_Pct","Precio_Sugerido","Precio_Publicado","Precio_Manual","HOT_DEAL","NEW_ARRIVAL","LOW_STOCK","MOQ_Final","ETA_Final","Alternativas"]].copy()
show.columns=["Oculto","Categoría","ITEM","Descripción","Proveedor elegido","Stock real","Stock público","Costo","Costo anterior","Variación costo %","Margen %","Precio sugerido","Precio publicado","Manual","HOT DEAL","NEW ARRIVAL","LOW STOCK","MOQ","ETA","Otros proveedores"]
st.dataframe(show,use_container_width=True,hide_index=True,column_config={
    "Costo":st.column_config.NumberColumn(format="$%.2f"),"Precio sugerido":st.column_config.NumberColumn(format="$%.2f"),
    "Precio publicado":st.column_config.NumberColumn(format="$%.2f"),"Costo anterior":st.column_config.NumberColumn(format="$%.2f"),
    "Variación costo %":st.column_config.NumberColumn(format="%.1f%%"),"Margen %":st.column_config.NumberColumn(format="%.2f%%")})

st.divider(); st.markdown("### Ajustar producto")
labels={f'{r["ITEM_PUBLICO"]} — {safe_text(r["Descripcion"])[:82]}':r["PRODUCT_KEY"] for _,r in view.iterrows()}
if not labels: st.stop()
sl=st.selectbox("Producto",list(labels.keys())); key=labels[sl]
row=winners[winners["PRODUCT_KEY"]==key].iloc[0]; opts=alternatives.get(key,pd.DataFrame()).copy(); ov=load_overrides().get(key,{})
left,right=st.columns([1.15,1])
with left:
    st.markdown("#### Oferta seleccionada")
    st.write(f'**ITEM:** {row["ITEM_PUBLICO"]}')
    st.write(f'**Proveedor:** {row["Proveedor"]}')
    st.write(f'**Stock real:** {int(row["Stock_Real"])} · **Stock público:** {row["Stock_Publico"]}')
    st.write(f'**Costo:** ${float(row["Costo"]):,.2f} · **MOQ:** {row["MOQ_Final"]} · **ETA:** {row["ETA_Final"]}')
    badges=[]
    if bool(row.get("HOT_DEAL",False)): badges.append("🔥 HOT DEAL")
    if bool(row.get("NEW_ARRIVAL",False)): badges.append("🆕 NEW ARRIVAL")
    if bool(row.get("LOW_STOCK",False)): badges.append("⚠️ LOW STOCK")
    if badges: st.info(" · ".join(badges))
    if pd.notna(row.get("Variacion_Costo_Pct")): st.caption(f'Cambio de costo vs. última publicación: {float(row["Variacion_Costo_Pct"]):+.1f}%')
    st.caption(safe_text(row["Descripcion"]))
    if len(opts)>1:
        alt=opts.copy(); alt["Seleccionado"]=[True]+[False]*(len(alt)-1)
        av=alt[["Seleccionado","Proveedor","ITEM_PUBLICO","Stock_Real","Costo","MOQ_Final","ETA_Final"]].copy()
        av.columns=["Seleccionado","Proveedor","ITEM","Stock","Costo","MOQ","ETA"]
        st.dataframe(av,use_container_width=True,hide_index=True,column_config={"Costo":st.column_config.NumberColumn(format="$%.2f")})
        first=opts.iloc[0]
        if (opts.iloc[1:]["Stock_Real"]>=2*first["Stock_Real"]).any(): st.info("Alternativa con mayor stock disponible.")
with right:
    st.markdown("#### Precio y visibilidad")
    margin_current=ov.get("manual_margin")
    if margin_current is None: margin_current=default_margin_pct(row.get("Categoria"),row.get("Costo"))
    margin=st.number_input("Margen %",min_value=0.0,max_value=100.0,value=float(margin_current or 0),step=0.5,key=f"m3m_{hashlib.md5(key.encode()).hexdigest()[:8]}")
    suggested=float(row["Costo"])*(1+margin/100); st.metric("Precio sugerido",f"${suggested:,.2f}")
    pub=st.number_input("Precio publicado",min_value=0.01,value=float(ov.get("manual_price") if ov.get("manual_price") is not None else suggested),step=1.0,format="%.2f",key=f"m3p_{hashlib.md5(key.encode()).hexdigest()[:8]}")
    hidden=st.checkbox("Ocultar este producto de la lista pública",value=bool(ov.get("hidden",0)),key=f"m3h_{hashlib.md5(key.encode()).hexdigest()[:8]}")
    cat_override=st.text_input("Categoría manual (opcional)",value=safe_text(ov.get("category_override")),key=f"m3c_{hashlib.md5(key.encode()).hexdigest()[:8]}")
    sub_override=st.text_input("Subcategoría manual (opcional)",value=safe_text(ov.get("subcategory_override")),key=f"m3s_{hashlib.md5(key.encode()).hexdigest()[:8]}")
    if st.button("Guardar cambios",type="primary",use_container_width=True):
        manual_price=float(pub) if abs(float(pub)-float(suggested))>0.005 else None
        save_override(key,manual_price,float(margin),hidden,cat_override.strip() or None,sub_override.strip() or None)
        st.success("Cambios guardados."); st.rerun()

st.caption("SQLite mantiene ajustes e historial durante la vida del contenedor. En Streamlit Community Cloud todavía migraremos la persistencia a una base externa antes de producción.")
