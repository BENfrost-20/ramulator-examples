import hashlib
import json
import sys
from pathlib import Path

xci = Path(sys.argv[1])
rtl = xci.parent / "rtl/ui/ddr4_v2_2_ui_cmd.sv"
expected = {
    "C0.DDR4_MemoryPart": "MTA18ASF2G72PZ-2G3",
    "C0.DDR4_Mem_Add_Map": "ROW_COLUMN_BANK_INTLV",
    "C0.DDR4_AxiAddressWidth": "34",
    "C0.DDR4_DataWidth": "72",
    "C0.DDR4_Ecc": "true",
    "C0.APP_ADDR_WIDTH": "31",
    "C0.APP_DATA_WIDTH": "512",
    "C0.DDR4_ROW_WIDTH": "17",
    "C0.DDR4_COLUMN_WIDTH": "10",
    "C0.DDR4_BANK_WIDTH": "2",
    "C0.DDR4_BANK_GROUP_WIDTH": "2",
    "C0.CS_WIDTH": "1",
}

def values(obj, key):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list):
            yield from (entry["value"] for entry in obj[key] if "value" in entry)
        for child in obj.values():
            yield from values(child, key)
    elif isinstance(obj, list):
        for child in obj:
            yield from values(child, key)

config = json.loads(xci.read_text())
print("field\tvalue")
for field, value in expected.items():
    actual = set(values(config, field))
    if actual != {value}:
        raise SystemExit(f"{field}: expected {value}, found {actual}")
    print(f"{field}\t{value}")
decoder_hash = hashlib.sha256(rtl.read_bytes()).hexdigest()
if decoder_hash != "519cd1e7e41488ab9d53aca542ae60e700f2bb0e7ef0a66a382be0e67ca268b2":
    raise SystemExit(f"DDR4 UI decoder changed: {decoder_hash}")
print(f"xci_sha256\t{hashlib.sha256(xci.read_bytes()).hexdigest()}")
print(f"ui_decoder_sha256\t{decoder_hash}")
