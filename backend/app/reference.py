"""Reference lookups that mirror the AS400 master files.

Kept as plain Python (not DB tables) because they are small, static and read-only for this
POC. `commodity_code_for()` is what turns the free-text `commodity` on an OS&D export row
into the official numeric code.
"""

from __future__ import annotations

# Official commodity master: code -> display value.
COMMODITIES: list[dict[str, str]] = [
    {"code": "3620", "description": "A/C UNIT"},
    {"code": "3715", "description": "AIR FILTERS"},
    {"code": "3720", "description": "AIRCRAFT OR MISSILE ENGINE PARTS"},
    {"code": "2080", "description": "ALCOHOLIC BEVERAGES, INCL LIQUOR"},
    {"code": "3431", "description": "ALUMINUM ITEMS"},
    {"code": "1960", "description": "AMMUNITION"},
    {"code": "2042", "description": "ANIMAL FEED"},
    {"code": "3714", "description": "AUTO, BUS, TRUCK PARTS, ACCESSORIES"},
    {"code": "2050", "description": "BAKERY PRODUCTS"},
    {"code": "3692", "description": "BATTERIES"},
    {"code": "2020", "description": "BEVERAGES"},
    {"code": "3650", "description": "BLINDS"},
    {"code": "3730", "description": "BOATS, PARTS, ACCESSORIES"},
    {"code": "2601", "description": "BOOKS"},
    {"code": "3423", "description": "BUILDING MATERIAL"},
    {"code": "3424", "description": "CABINETS"},
    {"code": "2070", "description": "CANDY & CONFECTIONERY"},
    {"code": "2270", "description": "CARPETS AND RUGS"},
    {"code": "2800", "description": "CHEMICALS"},
    {"code": "3260", "description": "CHINA OR POTTERY PRODUCTS"},
    {"code": "2110", "description": "CIGARETTES"},
    {"code": "3870", "description": "CLOCKS"},
    {"code": "2300", "description": "CLOTHING"},
    {"code": "2010", "description": "COFFEE & TEA"},
    {"code": "3670", "description": "COMPUTERS & RELATED EQUIPMENT"},
    {"code": "3436", "description": "COPPER/WIRE TUBING"},
    {"code": "2802", "description": "CUPS, STRAWS, LIDS, ETC"},
    {"code": "3403", "description": "DOORS"},
    {"code": "3600", "description": "ELECTRICAL MACHINERY, EQUIPMENT, SUPPLIES, NOI"},
    {"code": "0001", "description": "ELECTRONIC MEDIA, DVD'S, CD'S, BLANK OR RECORDED"},
    {"code": "0002", "description": "ELECTRONICS OTHER THAN TELEVISIONS"},
    {"code": "2892", "description": "EXPLOSIVES EXCEPT AMMUNITION"},
    {"code": "3520", "description": "FARM MACHINERY, IMPLEMENTS, PARTS"},
    {"code": "2025", "description": "FERTILIZER"},
    {"code": "3040", "description": "FIBERGLASS PRODUCTS"},
    {"code": "2507", "description": "FILING CABINETS"},
    {"code": "0003", "description": "FILM"},
    {"code": "1940", "description": "FIRE EXTINGUISHER"},
    {"code": "1950", "description": "FIREARMS"},
    {"code": "3002", "description": "FLOORING"},
    {"code": "2000", "description": "FOOD, INCLUDING PETS"},
    {"code": "3605", "description": "FURNACES, ELECTRIC OR GAS"},
    {"code": "2500", "description": "FURNITURE OR FIXTURES"},
    {"code": "2370", "description": "FURS AND FUR GOODS"},
    {"code": "3401", "description": "GARAGE DOORS"},
    {"code": "3210", "description": "GLASS FLAT OR BENT"},
    {"code": "3220", "description": "GLASSWARE AND GLASS PRODUCTS"},
    {"code": "2815", "description": "GLUE"},
    {"code": "3420", "description": "HARDWARE EXCEPT POWER TOOLS"},
    {"code": "0004", "description": "HOSE"},
    {"code": "3630", "description": "HOUSEHOLD APPLIANCES"},
    {"code": "3631", "description": "HOUSEHOLD GOODS, FIXTURES"},
    {"code": "2870", "description": "INSECTICIDES, FUNGICIDES, FERTILIZERS"},
    {"code": "3800", "description": "INSTRUMENTS, LABORATORY & OTHER NOI"},
    {"code": "3920", "description": "JANITORIAL SUPPLIES"},
    {"code": "3910", "description": "JEWELRY, SILVERWARE, FLATWARE"},
    {"code": "3110", "description": "LADDERS"},
    {"code": "3001", "description": "LAMINATES, COUNTER TOPS"},
    {"code": "3640", "description": "LAMPS, SHADES, ELECTRIC LIGHTING EQUIMENT, PARTS"},
    {"code": "3100", "description": "LEATHER & PRODUCTS"},
    {"code": "3500", "description": "MACHINERY, NOI"},
    {"code": "3280", "description": "MARBLE AND STONE PRODUCTS"},
    {"code": "2820", "description": "MEDICAL SUPPLIES"},
    {"code": "2830", "description": "MEDICINES, DRUGS, BIOLOGICAL PRODUCTS"},
    {"code": "3400", "description": "METAL PRODUCTS NOI"},
    {"code": "3300", "description": "METAL, SHEET, CASTING, FORGING, STAMPINGS"},
    {"code": "2801", "description": "MIRRORS DECORATIVE ACCESSORIES"},
    {"code": "3700", "description": "MOTORS"},
    {"code": "3570", "description": "OFFICE MACHINES, EQUIPMENT"},
    {"code": "0005", "description": "OIL WELL DRILLING TOOLS, OWDT"},
    {"code": "3830", "description": "OPTICAL LENSES AND INSTRUMENTS"},
    {"code": "2850", "description": "PAINTS, PAINT RELATED MATERIALS"},
    {"code": "3422", "description": "PANELING"},
    {"code": "2600", "description": "PAPER AND PAPER PRODUCTS"},
    {"code": "2045", "description": "PET SUPPLIES OTHER THAN FOOD"},
    {"code": "3860", "description": "PHOTO EQUIPMENT, CAMERAS, O/T FILM"},
    {"code": "3410", "description": "PIPE AND PIPE RELATED PRODUCTS"},
    {"code": "2075", "description": "PLANTS AND FLOWERS"},
    {"code": "3000", "description": "PLASTIC AND RUBBER PRODUCTS, NOI"},
    {"code": "3430", "description": "PLUMBING AND HEATING FIXTURES, SUPPLIES"},
    {"code": "3025", "description": "POOLS AND SPAS"},
    {"code": "2700", "description": "PRINTED MATTER INCLUDING INSERTS"},
    {"code": "0842", "description": "RUBBER, CRUDE GUM OR LATEX"},
    {"code": "3140", "description": "SHOES"},
    {"code": "2840", "description": "SOAPS, DETERGENTS, CLEANING COMPOUNDS"},
    {"code": "2605", "description": "STATIONARY SUPPLIES"},
    {"code": "3150", "description": "STEEL AND STEEL PRODUCTS"},
    {"code": "2380", "description": "TAPE"},
    {"code": "3651", "description": "TELEVISIONS"},
    {"code": "2390", "description": "TEXTILE PRODUCTS"},
    {"code": "0006", "description": "TILE"},
    {"code": "3010", "description": "TIRES & TUBES"},
    {"code": "2100", "description": "TOBACCO PRODUCTS OTHER THAN CIGARETTES"},
    {"code": "2844", "description": "TOILET PREPARATIONS, COSMETICS"},
    {"code": "3450", "description": "TOOLBOXES"},
    {"code": "3421", "description": "TOOLS ALL KINDS: MACHINE, HAND, POWER"},
    {"code": "3940", "description": "TOYS, GAMES & SPORTING GOODS"},
    {"code": "3635", "description": "VACUUM CLEANERS"},
    {"code": "3211", "description": "WINDSHIELDS"},
    {"code": "3435", "description": "WIRE AND CABLE"},
    {"code": "3610", "description": "WOOD STOVES"},
]

UNKNOWN_COMMODITY_CODE = "9999"
UNKNOWN_COMMODITY_DESCRIPTION = "UNKNOWN / NOT IN MASTER"

COMMODITY_BY_CODE: dict[str, str] = {c["code"]: c["description"] for c in COMMODITIES}
_BY_DESCRIPTION: dict[str, str] = {c["description"].upper(): c["code"] for c in COMMODITIES}


def commodity_code_for(description: str | None) -> str:
    """Resolve an export's free-text commodity to its official code."""
    key = (description or "").strip().upper()
    if not key:
        return UNKNOWN_COMMODITY_CODE
    return _BY_DESCRIPTION.get(key, UNKNOWN_COMMODITY_CODE)


def commodity_description_for(code: str | None) -> str:
    return COMMODITY_BY_CODE.get((code or "").strip(), UNKNOWN_COMMODITY_DESCRIPTION)


# Official terminal master.
TERMINALS: list[str] = [
    "ALO", "ANE", "ANW", "ATH", "ATL", "ATLRS", "AUG", "CTN", "CWM", "DFD",
    "FTM", "FUL", "JAX", "MGA", "MIA", "OCA", "ORL", "PUR", "SAV", "TAL",
    "TFT", "TPA", "VGA", "WPB", "WPBWM", "BIN", "BLM", "CGO", "CGOCA", "CRD",
    "DIA", "DMN", "DSM", "FND", "GBY", "GLK", "GLKCA", "GLKCD", "HWI", "LIL",
    "MAD", "MCC", "MKE", "MSP", "NEE", "OMN", "ORD", "PRU", "RIL", "WAU",
    "BKY", "CIN", "CMB", "DAY", "DET", "EIN", "FWN", "GRA", "GRY", "IND",
    "INDCA", "JKN", "LEX", "LIN", "LOU", "MIN", "SAG", "SBN", "TOL", "TOLCA",
    "TOLCE", "TOLCW", "TOLIL", "WMI", "WOO", "BIL", "BWI", "CHS", "CLT", "CLTCA",
    "CLTRS", "COL", "FAY", "FSC", "GBO", "GBORS", "GNC", "GSC", "GVL", "HGR",
    "HKY", "JCY", "KNX", "LOG", "MWV", "NRF", "NVA", "PRW", "PWV", "RAL",
    "RCM", "ROA", "STA", "ABL", "AMR", "AQE", "DLS", "DLSCA", "ELP", "ELPMX",
    "FAR", "FTW", "GRL", "GRLLO",
]

TERMINAL_SET = set(TERMINALS)
