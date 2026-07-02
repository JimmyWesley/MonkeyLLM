"""Build the Monkey Bench v1 corpus (forests/bench-forest/) + derived questions.

A deterministic, programmatically-expanded universe ("Telemetrix Systems",
distinct from the Phase-0 fixture): ~210 nodes, 15 branches, 2 SQLite
datasets. Facts are planted by the generator and the question set
(bench/questions-v2.json) is derived from the SAME fact tables — but with
paraphrase templates whose vocabulary is disjoint from the summary
templates (anti-leakage by construction, the roadmap's bench risk).

    python forests/scripts/build_bench_forest.py [--out forests/bench-forest]
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from monkeyllm.indexer import count_coverage, entry_line  # noqa: E402
from monkeyllm.parser import serialize_node  # noqa: E402

SEED = 2026
TODAY = "2026-06-10"
CREATED = "2026-05-01"
REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Pools (deterministic with SEED)
# ---------------------------------------------------------------------------

FIRST = ["Alice", "Bryan", "Claire", "Daniel", "Emma", "Frank", "Grace", "Henry",
         "Iris", "James", "Karen", "Liam", "Maria", "Nathan", "Olivia", "Peter",
         "Quinn", "Rachel", "Samuel", "Tina", "Uma", "Victor", "Wendy", "Xavier",
         "Yasmine", "Zoe", "Aaron", "Beth", "Carlos", "Diana", "Ethan", "Fiona",
         "George", "Hannah", "Ivan", "Julia"]
LAST = ["Anderson", "Brown", "Carter", "Davis", "Evans", "Foster", "Green", "Harris",
        "Irving", "Jones", "Klein", "Lewis", "Morgan", "Nelson", "Owen", "Parker",
        "Quinn", "Roberts", "Scott", "Turner", "Underwood", "Vincent", "Walker", "Ximenes"]
CITIES = [("Austin", "TX"), ("Seattle", "WA"), ("Denver", "CO"), ("Portland", "OR"),
          ("Boston", "MA"), ("Atlanta", "GA"), ("Chicago", "IL"), ("Phoenix", "AZ"),
          ("Miami", "FL"), ("Detroit", "MI"), ("Nashville", "TN"), ("Minneapolis", "MN")]
INSTITUTES = ["MIT Lincoln Laboratory", "Stanford AI Lab", "Carnegie Mellon CENSE",
              "Georgia Tech IRIM", "UTexas Applied Research", "Johns Hopkins APL"]
ROLES = ["firmware engineer", "data engineer", "AI researcher",
         "software architect", "quality analyst", "account manager",
         "data scientist", "reliability engineer", "embedded developer",
         "telemetry specialist"]
ORG_NAMES = ["AgriCore", "HarborNorth Logistics", "SunField Energy", "NetRetail Group",
             "GrainCo Cooperative", "TransRoute Freight", "Regional Health Network",
             "PeakMine Corp", "WindGrid Energy", "MeatPack Solutions",
             "ShipDock Marine", "TextilePro Mills", "PoultryFarm Inc",
             "DairyPure Industries", "AquaHarvest Corp", "Vineyard South Wines"]
SEGMENTS = ["agribusiness", "port logistics", "bioenergy", "retail", "cooperative",
            "road transport", "healthcare", "mining", "wind energy", "meatpacking",
            "naval", "textile", "poultry", "dairy", "commercial fishing", "viticulture"]
PRODUCT_DEFS = [
    ("Collar", "livestock telemetry collar for cattle"),
    ("Buoy", "water quality monitoring buoy"),
    ("Rover", "long-range vehicle tracker"),
    ("Gateway", "industrial LoRa gateway"),
    ("Vibe", "vibration sensor for predictive maintenance"),
    ("WeatherBox", "compact weather station"),
    ("Irrigo", "zone-based irrigation controller"),
    ("Wand", "yard RFID reader"),
    ("Probe", "silo level probe"),
    ("Dashboard", "factory floor panel"),
    ("SolarPack", "solar energy module for remote sensors"),
    ("ThermalEye", "embedded thermal camera"),
    ("NfcTag", "industrial NFC label"),
    ("Valve", "connected valve actuator"),
    ("EdgeKit", "edge computing kit for off-grid farms"),
    ("LightGrid", "smart warehouse lighting"),
    ("ColdLog", "cold chain logger"),
    ("WeighIn", "connected shipping scale"),
]
CONCEPT_DEFS = [
    ("lpwan", "LPWAN", "Family of long-range, low-power networks for remote sensors"),
    ("lorawan", "LoRaWAN", "Open LPWAN protocol with gateways and device classes A/B/C"),
    ("mqtt", "MQTT", "Lightweight publish/subscribe protocol for telemetry over TCP"),
    ("edge-computing", "Edge computing", "On-device processing near the sensor to reduce latency and bandwidth"),
    ("digital-twin", "Digital twin", "Virtual replica of a physical asset fed by live telemetry"),
    ("predictive-maintenance", "Predictive maintenance", "Intervention guided by signals (vibration, temperature) before failure"),
    ("cold-chain", "Cold chain", "Logistics with continuous product temperature control"),
    ("ota-update", "OTA update", "Remote over-the-air firmware update for device fleets"),
    ("mesh", "Mesh network", "Topology where nodes relay messages to one another"),
    ("nb-iot", "NB-IoT", "Licensed cellular LPWAN for stationary devices"),
    ("opc-ua", "OPC UA", "Interoperability standard for industrial data"),
    ("scada", "SCADA", "Supervisory control and data acquisition for industrial plants"),
    ("telemetry", "Telemetry", "Remote measurement and automatic transmission of physical quantities"),
    ("geofencing", "Geofencing", "Virtual boundary that triggers events on entry/exit"),
    ("dead-reckoning", "Dead reckoning", "Position estimation via inertial sensors when GPS fails"),
    ("fota-rollback", "Firmware rollback", "Automatic revert to the previous version when an OTA update fails"),
    ("binary-payload", "Binary payload", "Compact message encoding to conserve radio bandwidth"),
    ("duty-cycle", "Duty cycle", "Fraction of time a radio is allowed to transmit by regulation"),
    ("backhaul", "Backhaul", "Link that carries aggregated gateway traffic to the cloud"),
    ("provisioning", "Provisioning", "Secure registration of a new device on the platform"),
]
REGIONS = ["North", "Northeast", "Midwest", "Southeast", "West"]
QUARTERS = ["2026-Q1", "2026-Q2"]
DEFECTS = ["connector oxidation", "firmware boot loop", "broken antenna",
           "swollen battery", "failed seal", "spurious sensor reading"]
CHANNELS = ["direct", "partner", "tender"]

rng = random.Random(SEED)

# ---------------------------------------------------------------------------
# Fact tables
# ---------------------------------------------------------------------------

PEOPLE_AREAS = {  # branch fan-out control: <= 12 children per branch (A.5 navigability)
    "engineering": ["firmware engineer", "software architect", "embedded developer",
                    "reliability engineer", "quality analyst"],
    "data": ["data engineer", "data scientist", "AI researcher", "telemetry specialist"],
    "sales": ["account manager"],
}
PRODUCT_AREAS = ["field", "industry", "logistics"]


def build_universe():
    people = []
    names = [(f, l) for f in FIRST for l in LAST]
    rng.shuffle(names)
    areas = ["engineering"] * 12 + ["data"] * 12 + ["sales"] * 10
    for i in range(34):
        f, l = names[i]
        city, uf = rng.choice(CITIES)
        area = areas[i]
        people.append({
            "id": f"people/{area}/{f.lower()}-{l.lower()}", "first": f, "name": f"{f} {l}",
            "area": area, "role": rng.choice(PEOPLE_AREAS[area]), "city": city, "uf": uf,
            "institute": rng.choice(INSTITUTES) if rng.random() < 0.4 else None,
        })

    orgs = []
    for i, name in enumerate(ORG_NAMES):
        slug = name.lower().replace(" ", "-")
        group = "field-clients" if i % 2 == 0 else "industry-clients"
        orgs.append({"id": f"organizations/{group}/{slug}", "name": name,
                     "segment": SEGMENTS[i], "city": rng.choice(CITIES)[0]})

    products = []
    for i, (name, desc) in enumerate(PRODUCT_DEFS):
        sku = f"{chr(ord('K') + i % 8)}-{310 + i * 7}"
        area = PRODUCT_AREAS[i % 3]
        products.append({"id": f"products/{area}/{name.lower()}", "name": name, "sku": sku,
                         "desc": desc, "owner": people[i % len(people)]})

    projects = []
    for pid, (alias, goal) in enumerate([
        ("platform-drum", "telemetry ingestion and visualization platform"),
        ("firmware-beat", "common firmware, OTA, and provisioning for the full product line"),
        ("mesh-ring", "proprietary mesh network for farms without coverage"),
        ("pilot-rescue", "predictive maintenance pilot at a mining site"),
    ]):
        lead = people[10 + pid]
        projects.append({"id_base": f"projects/{alias}", "alias": alias, "goal": goal, "lead": lead})

    contracts = []
    month_names = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May"}
    for i in range(10):
        org = orgs[i]
        seller = people[20 + i % 6]
        prod = products[(i * 3) % len(products)]
        qty = rng.randrange(40, 400, 10)
        value = qty * rng.randrange(800, 2600, 50)
        month = (i % 5) + 1
        contracts.append({
            "id": f"events/contracts/2026-{month:02d}-deal-{org['id'].rsplit('/', 1)[1]}",
            "org": org, "seller": seller, "prod": prod, "qty": qty, "value": value,
            "month": month, "month_name": month_names[month], "day": (i * 3) % 27 + 1,
        })

    incidents = []
    for i in range(5):
        prod = products[(i * 5 + 2) % len(products)]
        defect = DEFECTS[i % len(DEFECTS)]
        count = rng.randrange(7, 90)
        incidents.append({
            "id": f"events/recalls/2026-0{i % 4 + 2}-recall-{prod['name'].lower()}",
            "prod": prod, "defect": defect, "count": count, "lote": f"L{rng.randrange(10, 60)}-{chr(65 + i)}",
        })

    releases = []
    for i, proj in enumerate(projects):
        ver = f"{i + 1}.{rng.randrange(0, 9)}"
        feature = rng.choice(["automatic firmware rollback support",
                              "6:1 payload compression",
                              "field QR-code provisioning",
                              "adaptive duty-cycle low-power mode"])
        releases.append({"id": f"events/releases/2026-04-version-{proj['alias']}",
                         "proj": proj, "ver": ver, "feature": feature})

    return people, orgs, products, projects, contracts, incidents, releases


# ---------------------------------------------------------------------------
# Datasets (ground truth computed for questions)
# ---------------------------------------------------------------------------

def build_sales_db(path: Path, products) -> dict:
    """sales/orders-2026.db — skewed so aggregates are unambiguous."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE orders (date TEXT, sku TEXT, product TEXT, region TEXT, channel TEXT, qty INTEGER, amount REAL)")
    weights = {"North": 0.6, "Northeast": 2.6, "Midwest": 0.9, "Southeast": 1.7, "West": 1.0}
    hot = products[4]  # Vibe — boosted so the top-SKU answer is unambiguous
    rows, totals, sku_rev = [], {r: 0.0 for r in REGIONS}, {}
    for i in range(900):
        prod = products[i % len(products)]
        region = REGIONS[i % len(REGIONS)]
        month = (i % 6) + 1
        qty = rng.randrange(1, 30)
        unit = rng.uniform(900, 2400) * weights[region] * (3.0 if prod is hot else 1.0)
        amount = round(qty * unit, 2)
        rows.append((f"2026-{month:02d}-{(i % 27) + 1:02d}", prod["sku"], prod["name"], region,
                     rng.choice(CHANNELS), qty, amount))
        totals[region] += amount
        sku_rev[prod["sku"]] = sku_rev.get(prod["sku"], 0.0) + amount
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    top_region = max(totals, key=totals.get)
    top_sku = max(sku_rev, key=sku_rev.get)
    return {"top_region": top_region, "top_region_total": totals[top_region],
            "top_sku": top_sku, "rows": len(rows)}


def build_support_db(path: Path, products) -> dict:
    """support/tickets-2026.db — ticket counts per product with causes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tickets (opened_at TEXT, product TEXT, sku TEXT, cause TEXT, severity TEXT, resolved INTEGER)")
    champ = products[7]  # Wand — most tickets, unambiguous
    rows, counts = [], {}
    for i in range(420):
        prod = champ if i % 3 == 0 else products[i % len(products)]
        cause = DEFECTS[i % len(DEFECTS)]
        rows.append((f"2026-{(i % 5) + 1:02d}-{(i % 27) + 1:02d}", prod["name"], prod["sku"],
                     cause, rng.choice(["low", "medium", "high"]), rng.random() < 0.8))
        counts[prod["name"]] = counts.get(prod["name"], 0) + 1
    conn.executemany("INSERT INTO tickets VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    top = max(counts, key=counts.get)
    return {"top_product": top, "top_count": counts[top], "rows": len(rows)}


# ---------------------------------------------------------------------------
# Forest writing
# ---------------------------------------------------------------------------

N: list[dict] = []


def node(id, type, title, summary, tags=(), links=(), body="", **extra):
    N.append({"id": id, "type": type, "title": title, "summary": summary,
              "tags": list(tags), "links": [{"rel": r, "target": t} for r, t in links],
              "body": body, "extra": extra})


def populate(people, orgs, products, projects, contracts, incidents, releases,
             sales_truth, support_truth):
    org_by_obj = {o["id"]: o for o in orgs}

    for p in people:
        inst = f" Came from {p['institute']}." if p["institute"] else ""
        node(p["id"], "entity", p["name"],
             f"{p['role'].capitalize()} at Telemetrix Systems. Lives in {p['city']} ({p['uf']}).{inst}",
             tags=["team"], links=[("related-to", "organizations/telemetrix-systems")],
             body=f"## Profile\n\n{p['name']} is a {p['role']} and lives in **{p['city']} ({p['uf']})**.{inst}\n\n## Involvement\n\nContributes to the telemetry product line at [[organizations/telemetrix-systems]].",
             entity_kind="person")

    node("organizations/telemetrix-systems", "entity", "Telemetrix Systems",
         "Austin-based manufacturer of hardware and industrial telemetry platform. Headquartered in Austin TX; line of 18 connected products.",
         tags=["company"], links=[],
         body="## About\n\nFounded in Austin. Develops sensors, gateways, and a telemetry platform.\n\n## Product line\n\nSee [[products/_index]].",
         entity_kind="organization")
    for o in orgs:
        node(o["id"], "entity", o["name"],
             f"Client in the {o['segment']} segment, based in {o['city']}. Purchases telemetry equipment from Telemetrix Systems.",
             tags=["client", o["segment"].split()[0]],
             links=[("related-to", "organizations/telemetrix-systems")],
             body=f"## About\n\n{o['name']} operates in {o['segment']} from {o['city']}.\n\n## Relationship\n\nActive client of [[organizations/telemetrix-systems]].",
             entity_kind="organization")

    for pr in products:
        own = pr["owner"]
        node(pr["id"], "entity", f"{pr['name']} ({pr['sku']})",
             f"{pr['desc'].capitalize()}, product code {pr['sku']}. Technical owner: {own['name']}.",
             tags=["product"], links=[("related-to", own["id"])],
             body=f"## Spec\n\n**{pr['name']}** is a {pr['desc']}. Catalog code: **{pr['sku']}**.\n\n## Owner\n\nEngineering under [[{own['id']}|{own['name']}]].",
             entity_kind="product")

    for proj in projects:
        base, lead = proj["id_base"], proj["lead"]
        node(f"{base}/vision", "note", f"Vision — {proj['alias']}",
             f"North star of the {proj['alias']} project: {proj['goal']}. Led by {lead['name']}.",
             tags=["project"], links=[("author", lead["id"])],
             body=f"## Goal\n\nBuild {proj['goal']}.\n\n## Leadership\n\nLed by [[{lead['id']}|{lead['name']}]].")
        node(f"{base}/architecture", "document", f"Architecture — {proj['alias']}",
             f"Technical design of {proj['alias']}: modules, data flow, and edge decisions. Authored by {lead['name']}.",
             tags=["project", "architecture"], links=[("author", lead["id"]), ("part-of", f"{base}/vision")],
             body=f"## Layers\n\nIngestion → queue → processing → API.\n\n## Authorship\n\nDesigned by [[{lead['id']}|{lead['name']}]], reviewed by the team.")
        node(f"{base}/decisions", "note", f"Decisions — {proj['alias']}",
             f"Decision log for {proj['alias']}: trade-offs, discarded alternatives, and open items.",
             tags=["project"], links=[("part-of", f"{base}/vision")],
             body="## Active decisions\n\n- Embedded database at the edge.\n- Compressed telemetry.\n\n## Open items\n\n- Backhaul retry strategy.")

    networks = {"lpwan", "lorawan", "mqtt", "mesh", "nb-iot", "opc-ua", "scada",
                "duty-cycle", "backhaul", "binary-payload"}
    for c, t, d in CONCEPT_DEFS:
        sub = "networks" if c in networks else "operations"
        node(f"concepts/{sub}/{c}", "concept", t, f"{d}.", tags=["concept"],
             body=f"## Definition\n\n{d}.\n\n## Use at Telemetrix\n\nAppears in telemetry products and platform projects.")

    for ct in contracts:
        o, s, pr = ct["org"], ct["seller"], ct["prod"]
        node(ct["id"], "event", f"Deal {o['name']} — {ct['month_name']} 2026",
             f"Contract closed on {ct['month_name']} {ct['day']}, 2026 with {o['name']}: {ct['qty']} units of {pr['name']} ({pr['sku']}). Value ${ct['value']:,.0f}. Seller: {s['name']}.",
             tags=["contract"], links=[("related-to", o["id"]), ("related-to", pr["id"]), ("mentioned-in", s["id"])],
             body=f"## Terms\n\n{o['name']} acquired **{ct['qty']} units** of {pr['name']} (code {pr['sku']}) for **${ct['value']:,.0f}**." +
                  f"\n\n## Handling\n\nNegotiation led by [[{s['id']}|{s['name']}]] via the direct channel.")

    month_names = {2: "February", 3: "March", 4: "April", 5: "May"}
    for inc in incidents:
        pr = inc["prod"]
        month = month_names[int(inc["id"].split("/")[-1].split("-")[1])]
        # A.4 curation: dated events carry their date in the summary (the
        # contract/release templates already do; recalls were the odd one out)
        node(inc["id"], "event", f"Recall of {pr['name']} — lot {inc['lote']}",
             f"Recall in {month} 2026 of {inc['count']} units of {pr['name']} ({pr['sku']}) for {inc['defect']}, lot {inc['lote']}. Free replacement within 30 days.",
             tags=["recall", "quality"], links=[("related-to", pr["id"])],
             body=f"## What happened\n\n**{inc['count']} units** of {pr['name']} exhibited **{inc['defect']}** (lot {inc['lote']}).\n\n## Action\n\nFull replacement; root cause in the assembly line.")

    for rel in releases:
        proj = rel["proj"]
        node(rel["id"], "event", f"Version {rel['ver']} — {proj['alias']}",
             f"April 2026 release of {proj['alias']}: version {rel['ver']} with {rel['feature']}.",
             tags=["release"], links=[("related-to", f"{proj['id_base']}/vision")],
             body=f"## What's new\n\nVersion **{rel['ver']}** delivered {rel['feature']}.\n\n## Context\n\nMilestone of [[{proj['id_base']}/vision|{proj['alias']}]].")

    node("sales/orders-2026", "dataset", "Orders 2026 (Jan–Jun)",
         f"Billed orders from January to June 2026: {sales_truth['rows']} rows with sku, product, region, channel, qty, and amount in USD. ERP export.",
         tags=["sales", "dataset"], links=[],
         body="## Query manual\n\n**Table:** `orders(date, sku, product, region, channel, qty, amount)`\n\n**Example queries:**\n- Revenue by region: `SELECT region, SUM(amount) AS total FROM orders GROUP BY region ORDER BY total DESC`\n- Revenue by product: `SELECT sku, product, SUM(amount) AS revenue FROM orders GROUP BY sku ORDER BY revenue DESC`",
         payload="orders-2026.db", payload_type="sqlite")
    node("support/tickets-2026", "dataset", "Support Tickets 2026",
         f"Support tickets for 2026: {support_truth['rows']} rows with product, sku, cause, severity, and resolution status.",
         tags=["support", "dataset"], links=[],
         body="## Query manual\n\n**Table:** `tickets(opened_at, product, sku, cause, severity, resolved)`\n\n**Example queries:**\n- Tickets by product: `SELECT product, COUNT(*) AS n FROM tickets GROUP BY product ORDER BY n DESC`\n- Most common causes: `SELECT cause, COUNT(*) FROM tickets GROUP BY cause ORDER BY 2 DESC`",
         payload="tickets-2026.db", payload_type="sqlite")

    node("notes/warranty-policy", "note", "Warranty Policy",
         "Standard warranty of 24 months for sensors and 36 months for gateways; recalls always with free replacement. Exceptions require board approval.",
         tags=["policy"], body="## Rule\n\n24 months (sensors), 36 months (gateways).\n\n## Recalls\n\nFree replacement, 30-day deadline.")
    node("notes/client-onboarding", "note", "Client Onboarding",
         "Step-by-step activation of a new client: device provisioning, training, and first assisted week.",
         tags=["process"], body="## Steps\n\n1. Provisioning ([[concepts/operations/provisioning]])\n2. Training\n3. Assisted week")
    node("infra/test-bench", "note", "Homologation Test Bench",
         "Radio and climate test bench: thermal chamber, attenuators, and reference gateways for classes A and C.",
         tags=["infra"], body="## Equipment\n\nThermal chamber, RF attenuators, reference gateways.\n\n## Use\n\nFirmware homologation before OTA ([[concepts/operations/ota-update]]).")


BRANCH_DEFS = {
    "people/_index": ("People", "Telemetrix Systems team by area: engineering, data, and sales."),
    "people/engineering/_index": ("Engineering", "Firmware, embedded software, reliability, and quality team."),
    "people/data/_index": ("Data & AI", "Data, data science, AI, and telemetry team."),
    "people/sales/_index": ("Sales", "Account managers who handle sales and contracts."),
    "organizations/_index": ("Organizations", "Telemetrix itself and its clients, grouped by profile."),
    "organizations/field-clients/_index": ("Field clients", "Clients in agribusiness, cooperatives, energy, and fishing."),
    "organizations/industry-clients/_index": ("Industry clients", "Clients in logistics, mining, healthcare, and manufacturing."),
    "products/_index": ("Products", "Connected hardware line, grouped by deployment environment."),
    "products/field/_index": ("Field products", "Sensors and kits for farms, water, and weather."),
    "products/industry/_index": ("Industrial products", "Sensors and panels for industrial plants."),
    "products/logistics/_index": ("Logistics products", "Trackers, readers, and shipping scales."),
    "projects/_index": ("Projects", "Internal initiatives: vision, architecture, and decisions per project."),
    "concepts/_index": ("Concepts", "Technical vocabulary, divided into networks and operations."),
    "concepts/networks/_index": ("Networks", "Protocols and radio: LPWAN, LoRaWAN, MQTT, mesh, backhaul."),
    "concepts/operations/_index": ("Operations", "Operations: OTA, predictive maintenance, cold chain, provisioning."),
    "events/_index": ("Events", "Dated facts, grouped into contracts, recalls, and releases."),
    "events/contracts/_index": ("Contracts", "Commercial deals closed with clients: quantities, values, and sellers."),
    "events/recalls/_index": ("Recalls", "Product recalls for manufacturing defects: product, lot, and cause."),
    "events/releases/_index": ("Releases", "Shipped project versions with main highlights."),
    "sales/_index": ("Sales", "Billed order datasets with SQL query manual."),
    "support/_index": ("Support", "Ticket datasets with causes and severity."),
    "infra/_index": ("Infra", "Test benches and homologation environments."),
    "notes/_index": ("Notes", "Internal policies and processes."),
}


def write_forest(out: Path):
    by_id = {n["id"]: n for n in N}
    for n in N:
        fm = {"id": n["id"], "type": n["type"], "title": n["title"], "summary": n["summary"],
              "created": CREATED, "updated": TODAY}
        if n["tags"]:
            fm["tags"] = n["tags"]
        if n["links"]:
            fm["links"] = n["links"]
        fm["source"] = "manual"
        fm.update(n["extra"])
        body = f"# {n['title']}\n\n{n['body'].strip()}\n"
        path = out / f"{n['id']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    branches = dict(BRANCH_DEFS)
    for nested_dir in sorted({n["id"].rsplit("/", 1)[0] for n in N if n["id"].count("/") == 2}):
        if f"{nested_dir}/_index" in branches:
            continue  # explicit BRANCH_DEFS win; this catches the project dirs
        alias = nested_dir.split("/")[1]
        branches[f"{nested_dir}/_index"] = (alias, f"Materials for the {alias} project: vision, architecture, and decisions.")

    def children_of(branch_id):
        folder = branch_id[: -len("/_index")]
        subs = [b for b in branches if b != branch_id and b[: -len("/_index")].rsplit("/", 1)[0] == folder]
        bananas = [nid for nid in sorted(by_id) if nid.rsplit("/", 1)[0] == folder]
        return sorted(subs), bananas

    for branch_id, (title, blurb) in branches.items():
        subs, bananas = children_of(branch_id)
        lines = [f"# {title}", "", f"> {blurb}", ""]
        if subs:
            lines.append("## Sub-branches")
            lines += [entry_line(s, branches[s][1]) for s in subs]
            lines.append("")
        lines.append("## Direct bananas")
        lines += [entry_line(b, by_id[b]["summary"]) for b in bananas]
        lines.append("")
        body = "\n".join(lines)
        fm = {"id": branch_id, "type": "branch", "title": title, "summary": blurb,
              "coverage": count_coverage(body), "created": CREATED, "updated": TODAY}
        path = out / f"{branch_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    top = sorted(b for b in branches if b.count("/") == 1)
    lines = ["# Telemetrix Knowledge Base", "",
             "> Telemetrix Systems knowledge base: team, clients, product line, "
             "projects, telemetry concepts, contracts, recalls, sales, and support.", "",
             "## Sub-branches"]
    lines += [entry_line(b, branches[b][1]) for b in top]
    lines += ["", "## Direct bananas", ""]
    body = "\n".join(lines)
    fm = {"id": "_index", "type": "branch", "title": "Telemetrix Knowledge Base",
          "summary": "Master branch of Telemetrix Systems: people, organizations, products, projects, concepts, events, sales, support, infra, and notes.",
          "coverage": count_coverage(body), "created": CREATED, "updated": TODAY}
    (out / "_index.md").write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")
    return len(N) + len(branches) + 1


# ---------------------------------------------------------------------------
# Questions v3 — chained tier (T06): the answer lives at the END of a chain of
# 3+ nodes the question never names directly. Each question carries a
# `min_hops` ground-truth annotation. Anti-leakage: the anchor vocabulary is
# paraphrased away from the summary templates, exactly like v2.
# ---------------------------------------------------------------------------

FEATURE_PARAPHRASE = {
    "automatic firmware rollback support":
        "the device rolls back to the previous version on its own when an update fails",
    "6:1 payload compression":
        "squeezing radio messages to one-sixth their original size",
    "field QR-code provisioning":
        "registering new devices on-site by scanning a code",
    "adaptive duty-cycle low-power mode":
        "saving battery by dynamically adjusting the transmission schedule",
}


def build_questions_v3(people, orgs, products, projects, contracts, incidents,
                       releases, sales_truth, support_truth) -> list[dict]:
    qs = []

    def q(question, expected, contains, min_hops):
        qs.append({"id": f"v3-{len(qs)+1:02d}", "question": question,
                   "expected_nodes": expected, "answer_contains": contains,
                   "min_hops": min_hops})

    # release -> project vision -> lead person (city): unique anchors only
    feat_counts = {}
    for rel in releases:
        feat_counts[rel["feature"]] = feat_counts.get(rel["feature"], 0) + 1
    chain_rels = [r for r in releases if feat_counts[r["feature"]] == 1][:3]
    for rel in chain_rels:
        lead = rel["proj"]["lead"]
        q(f"The project whose April highlight was {FEATURE_PARAPHRASE[rel['feature']]} "
          f"is led by whom, and in which city does that person live?",
          [rel["id"], f"{rel['proj']['id_base']}/vision", lead["id"]],
          [lead["first"], lead["city"]], 3)

    # recall (lot = rare exact token, sniff tier) -> product -> owner (city)
    for inc in incidents[:2]:
        owner = inc["prod"]["owner"]
        q(f"Lot {inc['lote']} was recalled from the market; who is technically responsible "
          f"for the device in that lot, and in which city does that person live?",
          [inc["id"], inc["prod"]["id"], owner["id"]],
          [owner["first"], owner["city"]], 3)

    # contract -> product -> technical owner (the contract only names the org)
    for ct in (contracts[3], contracts[5]):
        owner = ct["prod"]["owner"]
        q(f"The equipment that {ct['org']['name']} acquired in "
          f"{ct['month_name']} 2026 is maintained in engineering by whom?",
          [ct["id"], ct["prod"]["id"], owner["id"]],
          [owner["first"]], 3)

    # contract -> seller -> seller's city (city only exists in the person node)
    for ct in (contracts[6], contracts[8]):
        s = ct["seller"]
        q(f"The sale to {ct['org']['name']} was handled by which account manager, "
          f"and in which city is that person based?",
          [ct["id"], s["id"]], [s["first"], s["city"]], 3)

    # dataset join -> product node -> owner: SQL first, then the entity chain
    top_prod = next(p for p in products if p["sku"] == sales_truth["top_sku"])
    q("The product code that drove the highest revenue in the semester corresponds to "
      "which device, and who is its technical owner?",
      ["sales/orders-2026", top_prod["id"]],
      [top_prod["name"], top_prod["owner"]["first"]], 3)
    champ_prod = next(p for p in products if p["name"] == support_truth["top_product"])
    q("The product line item with the most support tickets in 2026 is technically "
      "the responsibility of whom, and in which city does that person work?",
      ["support/tickets-2026", champ_prod["id"], champ_prod["owner"]["id"]],
      [champ_prod["owner"]["first"], champ_prod["owner"]["city"]], 4)

    # release -> project -> lead -> origin institute (4 nodes deep)
    rel = releases[3]
    lead = rel["proj"]["lead"]
    if lead["institute"]:
        q(f"The project that released version {rel['ver']} in April is led by "
          f"someone who came from which institution?",
          [rel["id"], f"{rel['proj']['id_base']}/vision", lead["id"]],
          [lead["institute"].split()[-1]], 4)
    else:
        q(f"Who leads the project that released version {rel['ver']} in April, "
          f"and in which city does that person live?",
          [rel["id"], f"{rel['proj']['id_base']}/vision", lead["id"]],
          [lead["first"], lead["city"]], 3)

    return qs


# ---------------------------------------------------------------------------
# Questions v4 — the fork tier (T03): the entry is genuinely ambiguous, a
# correct answer requires walking `fork_width` INDEPENDENT sub-chains. v3
# questions all pin one chain (fork_width 1); these are built from the facts
# v3 rejects (shared features) plus unions/filters/negations over sets.
# ---------------------------------------------------------------------------

def build_questions_v4(people, orgs, products, projects, contracts, incidents,
                       releases, sales_truth, support_truth) -> list[dict]:
    qs = []

    def q(question, expected, contains, min_hops, fork_width):
        qs.append({"id": f"v4-{len(qs)+1:02d}", "question": question,
                   "expected_nodes": expected, "answer_contains": contains,
                   "min_hops": min_hops, "fork_width": fork_width})

    # 1. shared-feature fork: exactly the releases v3 excludes (feature in 2+
    #    projects) — each project is an independent release -> vision -> lead chain
    feat_counts = {}
    for rel in releases:
        feat_counts[rel["feature"]] = feat_counts.get(rel["feature"], 0) + 1
    for feature in sorted(f for f, c in feat_counts.items() if c > 1):
        twins = [r for r in releases if r["feature"] == feature]
        expected = []
        contains = []
        for r in twins:
            expected += [r["id"], f"{r['proj']['id_base']}/vision"]
            contains += [r["proj"]["alias"], r["proj"]["lead"]["first"]]
        q(f"More than one project shipped {FEATURE_PARAPHRASE[feature]} in its "
          f"April release. Which projects were they, and who leads each one?",
          expected, contains, 3, len(twins))

    # 2. union over early recalls: one recall -> product -> owner chain each
    early = [i for i in incidents if int(i["id"].split("/")[-1].split("-")[1]) <= 3]
    q("Some products were recalled in February and March 2026. In which cities "
      "do the technical owners of those products live?",
      [i["id"] for i in early] + [i["prod"]["owner"]["id"] for i in early],
      sorted({i["prod"]["owner"]["city"] for i in early}), 3, len(early))

    # 3. filter over contracts: a product bought by 2+ different clients
    by_prod: dict[str, list] = {}
    for ct in contracts:
        by_prod.setdefault(ct["prod"]["name"], []).append(ct)
    repeat_prod = next(name for name, cts in sorted(by_prod.items())
                       if len({c["org"]["id"] for c in cts}) >= 2)
    cts = by_prod[repeat_prod]
    q(f"Which clients acquired the {repeat_prod} during 2026, and in which "
      f"month did each deal close?",
      [c["id"] for c in cts],
      sorted({c["org"]["name"] for c in cts}) + sorted({c["month_name"] for c in cts}),
      2, len(cts))

    # 4. intersection: one seller, two clients, same device
    seller_pair = next(
        (cts for cts in by_prod.values()
         if len(cts) >= 2 and len({c["seller"]["id"] for c in cts}) == 1
         and len({c["org"]["id"] for c in cts}) >= 2),
        None)
    if seller_pair:
        a, b = seller_pair[0], seller_pair[1]
        q(f"The deals with {a['org']['name']} and {b['org']['name']} were closed "
          f"by the same account manager. Who is it, and which device did both "
          f"clients buy?",
          [a["id"], b["id"], a["seller"]["id"]],
          [a["seller"]["first"], a["prod"]["name"]], 2, 2)

    # 5. attribute scan over the project leads (institute lives ONLY in the
    #    person node — every lead must be visited)
    with_inst = [p for p in projects if p["lead"]["institute"]]
    if with_inst:
        q("Which of the project leads joined Telemetrix from research "
          "institutions, and from which institution did each one come?",
          [f"{p['id_base']}/vision" for p in projects] +
          [p["lead"]["id"] for p in with_inst],
          sorted(p["lead"]["first"] for p in with_inst), 3, len(projects))

    # 6. negation over the same set: proving "none" requires the full scan
    without_inst = [p for p in projects if not p["lead"]["institute"]]
    if without_inst:
        q("Which project is led by someone who did NOT come from a research "
          "institution?",
          [f"{p['id_base']}/vision" for p in without_inst] +
          [p["lead"]["id"] for p in without_inst],
          [without_inst[0]["alias"]], 3, len(projects))

    # 7. cross-dataset fork: two independent SQL chains (sales + support)
    champ_prod = next(p for p in products if p["name"] == support_truth["top_product"])
    q("Which sales region billed the most in the semester, and which product "
      "line generated the most support tickets?",
      ["sales/orders-2026", "support/tickets-2026"],
      [sales_truth["top_region"], champ_prod["name"]], 2, 2)

    # 8. union over one seller's portfolio: each contract is its own chain
    # (skip the seller already starring in question 4 — no duplicate chains)
    by_seller: dict[str, list] = {}
    for ct in contracts:
        by_seller.setdefault(ct["seller"]["id"], []).append(ct)
    used_seller = seller_pair[0]["seller"]["id"] if seller_pair else None
    busy = max((cts for sid, cts in sorted(by_seller.items()) if sid != used_seller),
               key=len)
    q(f"{busy[0]['seller']['name']} closed several deals in 2026 — with which "
      f"clients?",
      [c["id"] for c in busy] + [busy[0]["seller"]["id"]],
      sorted({c["org"]["name"] for c in busy}), 2, len(busy))

    return qs


# ---------------------------------------------------------------------------
# Questions v2 — paraphrase templates with vocabulary disjoint from summaries
# ---------------------------------------------------------------------------

def build_questions(people, products, projects, contracts, incidents, releases,
                    sales_truth, support_truth) -> list[dict]:
    qs = []

    def q(qid, question, expected, contains):
        qs.append({"id": qid, "question": question,
                   "expected_nodes": expected, "answer_contains": contains})

    # author-of-project -> city (summaries say "Led by / Lives in"; questions say "at the helm / resides")
    for i, proj in enumerate(projects[:3]):
        lead = proj["lead"]
        q(f"q{len(qs)+1:02d}",
          f"Who is at the helm of {proj['alias']} and in what city does that person reside?",
          [f"{proj['id_base']}/vision", lead["id"]],
          [lead["first"], lead["city"]])

    # contracts (summaries: "Contract closed... Seller:"; questions: "deal/who handled")
    for ct in contracts[:3]:
        q(f"q{len(qs)+1:02d}",
          f"In {ct['month_name']} 2026 {ct['org']['name']} took which equipment, in what quantity, and who handled the sale?",
          [ct["id"]],
          [ct["prod"]["name"], str(ct["qty"]), ct["seller"]["first"]])

    # recalls (summaries: "Recall of N units for <defect>"; questions: "returned/issue")
    for inc in incidents[:2]:
        q(f"q{len(qs)+1:02d}",
          f"The {inc['prod']['name']} had a manufacturing issue in 2026: how many units came back and what was the defect?",
          [inc["id"]],
          [str(inc["count"]), inc["defect"].split()[0]])

    # releases
    for rel in releases[:2]:
        q(f"q{len(qs)+1:02d}",
          f"The April release of {rel['proj']['alias']} shipped with which version number and what main feature?",
          [rel["id"]],
          [rel["ver"]])

    # dataset aggregates (need SQL)
    q(f"q{len(qs)+1:02d}",
      "Considering everything billed in the first half of 2026, which region led total revenue?",
      ["sales/orders-2026"],
      [sales_truth["top_region"]])
    q(f"q{len(qs)+1:02d}",
      "Which product code drove the highest revenue in the semester, according to the orders database?",
      ["sales/orders-2026"],
      [sales_truth["top_sku"]])
    q(f"q{len(qs)+1:02d}",
      "Which product line item generated the most support tickets in 2026?",
      ["support/tickets-2026"],
      [support_truth["top_product"]])

    # product SKU lookups (summaries: "product code"; questions: "catalog reference")
    for pr in (products[2], products[9]):
        q(f"q{len(qs)+1:02d}",
          f"What is the catalog reference of {pr['name']} and who is technically responsible for it?",
          [pr["id"]],
          [pr["sku"], pr["owner"]["first"]])

    # person origin institute
    cands = [p for p in people if p["institute"]]
    for p in cands[:2]:
        q(f"q{len(qs)+1:02d}",
          f"From which institution did {p['name']} come before joining Telemetrix, and what is their role today?",
          [p["id"]],
          [p["institute"].split()[-1]])

    # policy multi-hop (note)
    q(f"q{len(qs)+1:02d}",
      "When an entire batch has a defect, what does the company policy guarantee to the customer and within what timeframe?",
      ["notes/warranty-policy"],
      ["30"])

    return qs


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "forests" / "bench-forest"))
    ap.add_argument("--questions-out", default=str(REPO / "bench" / "questions-v2.json"))
    ap.add_argument("--questions-v3-out", default=str(REPO / "bench" / "questions-v3.json"))
    ap.add_argument("--questions-v4-out", default=str(REPO / "bench" / "questions-v4.json"))
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        def _clear_readonly(func, path, exc):
            import os, stat
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(out, onexc=_clear_readonly)
    out.mkdir(parents=True)

    people, orgs, products, projects, contracts, incidents, releases = build_universe()
    sales_truth = build_sales_db(out / "sales" / "orders-2026.db", products)
    support_truth = build_support_db(out / "support" / "tickets-2026.db", products)
    populate(people, orgs, products, projects, contracts, incidents, releases,
             sales_truth, support_truth)
    total = write_forest(out)

    questions = build_questions(people, products, projects, contracts, incidents,
                                releases, sales_truth, support_truth)
    Path(args.questions_out).write_text(
        json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    questions_v3 = build_questions_v3(people, orgs, products, projects, contracts,
                                      incidents, releases, sales_truth, support_truth)
    Path(args.questions_v3_out).write_text(
        json.dumps(questions_v3, ensure_ascii=False, indent=2), encoding="utf-8")
    questions_v4 = build_questions_v4(people, orgs, products, projects, contracts,
                                      incidents, releases, sales_truth, support_truth)
    Path(args.questions_v4_out).write_text(
        json.dumps(questions_v4, ensure_ascii=False, indent=2), encoding="utf-8")

    def git(*a):
        subprocess.run(["git", "-C", str(out), "-c", "user.name=bench", "-c",
                        "user.email=bench@monkeyllm.local", *a],
                       check=True, capture_output=True, text=True)
    git("init", "--quiet")
    # spec A.3.1: binaries never enter the forest git (referenced by payload_hash)
    (out / ".gitignore").write_text(
        "_derived/\n.vine.lock\n*.db\n*.sqlite\n_assets/\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "--quiet", "-m", f"bench forest: {total} nodes, 2 datasets")

    print(f"bench forest: {total} nodes at {out}")
    print(f"sales ground truth: top region={sales_truth['top_region']}, top SKU={sales_truth['top_sku']}")
    print(f"support ground truth: top product={support_truth['top_product']} ({support_truth['top_count']})")
    print(f"{len(questions)} questions at {args.questions_out}")
    deep = sum(1 for x in questions_v3 if x["min_hops"] >= 3)
    print(f"{len(questions_v3)} v3 questions at {args.questions_v3_out} "
          f"({deep} with min_hops >= 3)")
    forked = sum(1 for x in questions_v4 if x["fork_width"] >= 2)
    print(f"{len(questions_v4)} v4 questions at {args.questions_v4_out} "
          f"({forked} with fork_width >= 2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
