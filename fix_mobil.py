"""
fix_mobil.py - Lägger till mobilresponsiv CSS på rätt sätt.
Kör EFTER att git checkout återställt index.html.
python fix_mobil.py
"""
from pathlib import Path

f = Path(__file__).parent / "templates" / "index.html"
content = f.read_text(encoding="utf-8")

mobil_css = """
/* ── MOBILRESPONSIVT ──────────────────────────────────── */
@media(max-width:768px){
  .two-col,.three-col,.cgrid{grid-template-columns:1fr}
  .system-grid{grid-template-columns:repeat(4,1fr)}
  main{padding:10px}
}
@media(max-width:540px){
  nav{padding:9px 11px 0}
  .logo{font-size:1.6rem}
  .nav-top{gap:7px}
  .nav-right{gap:4px}
  input[type=date]{width:120px;font-size:.68rem}
  .btn{font-size:.68rem;padding:5px 9px}
  .tabs{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none}
  .tab{font-size:.63rem;padding:7px 9px;white-space:nowrap}
  .grid,.summary-grid{grid-template-columns:repeat(2,1fr);gap:7px}
  .system-grid{grid-template-columns:repeat(2,1fr);gap:5px}
  .tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  table{min-width:400px}
  .lopp-btn{font-size:.88rem;padding:6px 10px}
  .filter-bar{padding:7px 9px;gap:6px;row-gap:6px}
  select{font-size:.68rem}
  main{padding:8px}
  .bar-label{width:80px;font-size:.67rem}
}
@media(max-width:360px){
  .grid{grid-template-columns:1fr}
  .logo{font-size:1.3rem}
}
"""

# Lägg till CSS FÖRE </style> (inte ersätt hela taggen)
if mobil_css.strip() in content:
    print("Mobil-CSS redan tillagd!")
elif "</style>" in content:
    content = content.replace("</style>", mobil_css + "\n</style>", 1)
    f.write_text(content, encoding="utf-8")
    print(f"✓ Mobil-CSS tillagd ({len(content)} tecken totalt)")
else:
    print("✗ Kunde inte hitta </style>")
