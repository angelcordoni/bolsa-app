"""Genera lists.js con las listas de valores del mercado. Ejecutar: python3 tools/build_lists.py"""
import csv, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
sp500 = [r["Symbol"].replace(".", "-") for r in csv.DictReader(open(os.path.join(HERE, "sp500.csv"), encoding="utf-8"))]
nasdaq100 = """AAPL MSFT NVDA AMZN META GOOGL GOOG AVGO TSLA COST NFLX PLTR AMD ASML CSCO TMUS AZN PEP LIN ISRG INTU TXN QCOM AMGN ADBE BKNG PDD AMAT HON ARM GILD PANW CMCSA ADP LRCX MU APP ADI CRWD KLAC VRTX SBUX MELI INTC CEG DASH MSTR CDNS SNPS ORLY CTAS MAR ABNB FTNT MDLZ PYPL ADSK REGN AXON WDAY ROP MNST CSX AEP CHTR NXPI PCAR FAST PAYX TTWO KDP ZS IDXX CPRT ROST EXC DDOG XEL VRSK FANG CCEP BKR EA TEAM KHC MCHP ODFL CSGP LULU GEHC CTSH DXCM TTD ANSS WBD CDW BIIB ON GFS LIN SHOP""".split()
dow30 = """AAPL AMGN AMZN AXP BA CAT CRM CSCO CVX DIS GS HD HON IBM JNJ JPM KO MCD MMM MRK MSFT NKE NVDA PG SHW TRV UNH V VZ WMT""".split()
ibex35 = """ACS.MC ACX.MC AENA.MC AMS.MC ANA.MC ANE.MC BBVA.MC BKT.MC CABK.MC CLNX.MC COL.MC ELE.MC ENG.MC FDR.MC FER.MC GRF.MC IAG.MC IBE.MC IDR.MC ITX.MC LOG.MC MAP.MC MRL.MC MTS.MC NTGY.MC PUIG.MC RED.MC REP.MC ROVI.MC SAB.MC SAN.MC SCYR.MC SLR.MC TEF.MC UNI.MC""".split()
etfs = """SPY VOO IVV VTI QQQ QQQM DIA IWM VT VEA VWO EFA EEM IEFA IEMG VUG VTV SCHD VIG VYM SCHG JEPI JEPQ XLK XLF XLE XLV XLY XLP XLI XLU XLB XLRE XLC SMH SOXX ARKK GLD SLV IAU TLT IEF SHY BND AGG LQD HYG VNQ IBIT ETHA EWZ EWW EWP EWG EWJ FXI INDA""".split()
populares = """SPY QQQ VOO VTI IWM DIA VT GLD XLE XLF AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA KO PEP JNJ PG XOM WMT COST SAN.MC ITX.MC IBE.MC BBVA.MC""".split()
def uniq(xs):
    seen = set(); return [x for x in xs if not (x in seen or seen.add(x))]
todo = uniq(populares + sp500 + nasdaq100 + dow30 + ibex35 + etfs)
lists = [
    {"id": "todo", "name": "Todo el mercado", "symbols": todo},
    {"id": "companias", "name": "Compañías", "symbols": [x for x in todo if x not in set(etfs)]},
    {"id": "populares", "name": "Populares", "symbols": uniq(populares)},
    {"id": "sp500", "name": "S&P 500", "symbols": uniq(sp500)},
    {"id": "nasdaq100", "name": "Nasdaq 100", "symbols": uniq(nasdaq100)},
    {"id": "dow30", "name": "Dow Jones 30", "symbols": uniq(dow30)},
    {"id": "ibex35", "name": "IBEX 35", "symbols": uniq(ibex35)},
    {"id": "etfs", "name": "ETFs", "symbols": uniq(etfs)},
]
out = "// Generado por tools/build_lists.py\nwindow.MARKET_LISTS = " + json.dumps(lists, separators=(",", ":")) + ";\n"
open(os.path.join(HERE, "..", "lists.js"), "w", encoding="utf-8").write(out)
print({l["name"]: len(l["symbols"]) for l in lists})
