"""API-level (id >= 0x800000) symbols in a compiled program's symbol table
that are absent from a given device's own api.debug.xml.

usage: apisyms.py <prg.debug.xml> <device>

<device>'s api.debug.xml is read from vendor/devices/<device>/<device>.api.debug.xml,
resolved relative to the repo root (override with the CIQ_VENDOR_DEVICES env var).
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
VENDOR = Path(os.environ.get("CIQ_VENDOR_DEVICES", REPO_ROOT / "vendor" / "devices"))

t = open(sys.argv[1]).read()
tab = t[t.index('<symbolTable>'):t.index('</symbolTable>')]
dev = sys.argv[2]
api = (VENDOR / dev / f"{dev}.api.debug.xml").read_text()
names = (set(re.findall(r'name="([^"]+)"', api))
         | set(re.findall(r'symbolId="([^"]+)"', api))
         | set(re.findall(r'classId="([^"]+)"', api))
         | set(re.findall(r'symbol="([^"]+)"', api)))
syms = [s for i, s in re.findall(r'id="(\d+)"[^>]*symbol="([^"]+)"', tab) if int(i) >= 0x800000]
print('absent:', sorted(s for s in syms if s not in names))
