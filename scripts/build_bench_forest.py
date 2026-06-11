"""Build the Monkey Bench v1 corpus (bench-forest/) + derived questions.

A deterministic, programmatically-expanded universe ("Maracatu Sistemas",
distinct from the Phase-0 fixture): ~210 nodes, 15 branches, 2 SQLite
datasets. Facts are planted by the generator and the question set
(bench/questions-v2.json) is derived from the SAME fact tables — but with
paraphrase templates whose vocabulary is disjoint from the summary
templates (anti-leakage by construction, the roadmap's bench risk).

    python scripts/build_bench_forest.py [--out bench-forest]
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monkeyllm.indexer import count_coverage, entry_line  # noqa: E402
from monkeyllm.parser import serialize_node  # noqa: E402

SEED = 2026
TODAY = "2026-06-10"
CREATED = "2026-05-01"
REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Pools (deterministic with SEED)
# ---------------------------------------------------------------------------

FIRST = ["Aurora", "Benício", "Clarice", "Davi", "Estela", "Felipe", "Gilda", "Heitor",
         "Iara", "João", "Kátia", "Luan", "Mariana", "Nelson", "Otávia", "Paulo",
         "Quitéria", "Rafael", "Sônia", "Tales", "Úrsula", "Vicente", "Wanda", "Xavier",
         "Yasmin", "Zeca", "Amélia", "Bento", "Cecília", "Dorival", "Eunice", "Firmino",
         "Graça", "Hugo", "Ivone", "Jandira"]
LAST = ["Albuquerque", "Barros", "Cavalcanti", "Drummond", "Espíndola", "Furtado",
        "Guimarães", "Holanda", "Itaparica", "Junqueira", "Klein", "Lacerda",
        "Maranhão", "Negreiros", "Onofre", "Peixoto", "Queiroz", "Rabelo",
        "Sarmento", "Trindade", "Uchoa", "Vasconcelos", "Wanderley", "Ximenes"]
CITIES = [("Recife", "PE"), ("Olinda", "PE"), ("Fortaleza", "CE"), ("Salvador", "BA"),
          ("São Paulo", "SP"), ("Campinas", "SP"), ("Curitiba", "PR"), ("Florianópolis", "SC"),
          ("Belo Horizonte", "MG"), ("Manaus", "AM"), ("Belém", "PA"), ("Natal", "RN")]
INSTITUTES = ["Instituto Caatinga de Computação", "Laboratório Mangue Digital",
              "Centro Sertão de IA", "Núcleo Atlântico de Dados",
              "Faculdade Boa Viagem", "Politécnica do Capibaribe"]
ROLES = ["engenheira de firmware", "engenheiro de dados", "pesquisadora de IA",
         "arquiteto de software", "analista de qualidade", "gerente de contas",
         "cientista de dados", "engenheira de confiabilidade", "desenvolvedor embarcado",
         "especialista em telemetria"]
ORG_NAMES = ["AgroVale", "PortoNorte Logística", "Usina Catende Digital", "RedeFrevo Varejo",
             "Cooperativa Mandacaru", "TransSertão Cargas", "Hospital Beberibe",
             "Mineradora Gurjaú", "EnergiaJangada", "Frigorífico Asa Branca",
             "Estaleiro Pina", "Têxtil Caruaru", "Granja Aratu", "Laticínios Garanhuns",
             "Pesqueira Atlântico Sul", "Vinícola São Francisco"]
SEGMENTS = ["agronegócio", "logística portuária", "bioenergia", "varejo", "cooperativismo",
            "transporte rodoviário", "saúde", "mineração", "energia eólica", "frigorífico",
            "naval", "têxtil", "avicultura", "laticínios", "pesca industrial", "vitivinicultura"]
PRODUCT_DEFS = [
    ("Faro", "coleira de telemetria para rebanho bovino"),
    ("Mangue", "boia de monitoramento de qualidade de água"),
    ("Xote", "rastreador veicular de longa autonomia"),
    ("Frevo", "gateway LoRa industrial"),
    ("Cangaço", "sensor de vibração para manutenção preditiva"),
    ("Jangada", "estação meteorológica compacta"),
    ("Maracatu", "controlador de irrigação por zona"),
    ("Caboclo", "leitor RFID de pátio"),
    ("Arrecife", "sonda de nível para silos"),
    ("Quadrilha", "painel de chão de fábrica"),
    ("Forró", "módulo de energia solar para sensores remotos"),
    ("Baião", "câmera térmica embarcada"),
    ("Cordel", "etiqueta NFC industrial"),
    ("Capoeira", "atuador de válvula conectado"),
    ("Sertão", "kit de borda para fazendas sem internet"),
    ("Lampião", "iluminação inteligente de galpão"),
    ("Acerola", "registrador de cadeia fria"),
    ("Tapioca", "balança conectada de expedição"),
]
CONCEPT_DEFS = [
    ("lpwan", "LPWAN", "Família de redes de longo alcance e baixa potência para sensores remotos"),
    ("lorawan", "LoRaWAN", "Protocolo LPWAN aberto com gateways e classes A/B/C de dispositivo"),
    ("mqtt", "MQTT", "Protocolo publish/subscribe leve para telemetria sobre TCP"),
    ("edge-computing", "Edge computing", "Processamento na borda, perto do sensor, para reduzir latência e banda"),
    ("digital-twin", "Digital twin", "Réplica virtual de um ativo físico alimentada por telemetria"),
    ("manutencao-preditiva", "Manutenção preditiva", "Intervenção guiada por sinais (vibração, temperatura) antes da falha"),
    ("cadeia-fria", "Cadeia fria", "Logística com controle contínuo de temperatura do produto"),
    ("ota-update", "Atualização OTA", "Atualização de firmware remota, por rádio, em frotas de dispositivos"),
    ("mesh", "Rede mesh", "Topologia onde nós retransmitem mensagens uns dos outros"),
    ("nb-iot", "NB-IoT", "LPWAN celular licenciada para dispositivos estacionários"),
    ("opc-ua", "OPC UA", "Padrão de interoperabilidade para dados industriais"),
    ("scada", "SCADA", "Supervisão e aquisição de dados de plantas industriais"),
    ("telemetria", "Telemetria", "Medição remota e transmissão automática de grandezas físicas"),
    ("geofencing", "Geofencing", "Cerca virtual que dispara eventos ao entrar/sair de um perímetro"),
    ("dead-reckoning", "Dead reckoning", "Estimativa de posição por sensores inerciais quando o GPS falha"),
    ("fota-rollback", "Rollback de firmware", "Retorno automático à versão anterior quando o OTA falha"),
    ("payload-binario", "Payload binário", "Codificação compacta de mensagens para economizar rádio"),
    ("duty-cycle", "Duty cycle", "Fração de tempo em que um rádio pode transmitir por regulação"),
    ("backhaul", "Backhaul", "Enlace que leva o tráfego agregado dos gateways à nuvem"),
    ("provisionamento", "Provisionamento", "Registro seguro de um dispositivo novo na plataforma"),
]
REGIONS = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
QUARTERS = ["2026-Q1", "2026-Q2"]
DEFECTS = ["oxidação no conector", "firmware travando no boot", "antena rompida",
           "bateria inchada", "vedação comprometida", "leitura espúria do sensor"]
CHANNELS = ["direto", "parceiro", "licitação"]

rng = random.Random(SEED)

# ---------------------------------------------------------------------------
# Fact tables
# ---------------------------------------------------------------------------

PEOPLE_AREAS = {  # branch fan-out control: <= 12 children per branch (A.5 navigability)
    "engenharia": ["engenheira de firmware", "arquiteto de software", "desenvolvedor embarcado",
                   "engenheira de confiabilidade", "analista de qualidade"],
    "dados": ["engenheiro de dados", "cientista de dados", "pesquisadora de IA",
              "especialista em telemetria"],
    "comercial": ["gerente de contas"],
}
PRODUCT_AREAS = ["campo", "industria", "logistica"]


def build_universe():
    people = []
    names = [(f, l) for f in FIRST for l in LAST]
    rng.shuffle(names)
    areas = ["engenharia"] * 12 + ["dados"] * 12 + ["comercial"] * 10
    for i in range(34):
        f, l = names[i]
        city, uf = rng.choice(CITIES)
        area = areas[i]
        people.append({
            "id": f"pessoas/{area}/{f.lower()}-{l.lower()}", "first": f, "name": f"{f} {l}",
            "area": area, "role": rng.choice(PEOPLE_AREAS[area]), "city": city, "uf": uf,
            "institute": rng.choice(INSTITUTES) if rng.random() < 0.4 else None,
        })

    orgs = []
    for i, name in enumerate(ORG_NAMES):
        slug = name.lower().replace(" ", "-").replace("ô", "o").replace("í", "i").replace("é", "e").replace("ã", "a").replace("ç", "c").replace("ê", "e")
        group = "clientes-campo" if i % 2 == 0 else "clientes-industria"
        orgs.append({"id": f"organizacoes/{group}/{slug}", "name": name,
                     "segment": SEGMENTS[i], "city": rng.choice(CITIES)[0]})

    products = []
    for i, (name, desc) in enumerate(PRODUCT_DEFS):
        sku = f"{chr(ord('K') + i % 8)}-{310 + i * 7}"
        area = PRODUCT_AREAS[i % 3]
        products.append({"id": f"produtos/{area}/{name.lower()}", "name": name, "sku": sku,
                         "desc": desc, "owner": people[i % len(people)]})

    projects = []
    for pid, (alias, goal) in enumerate([
        ("plataforma-tambor", "plataforma de ingestão e visualização de telemetria"),
        ("firmware-zabumba", "firmware comum, OTA e provisionamento de toda a linha"),
        ("malha-ciranda", "rede mesh proprietária para fazendas sem cobertura"),
        ("piloto-resgate", "piloto de manutenção preditiva em mineradora"),
    ]):
        lead = people[10 + pid]
        projects.append({"id_base": f"projetos/{alias}", "alias": alias, "goal": goal, "lead": lead})

    contracts = []
    month_names = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio"}
    for i in range(10):
        org = orgs[i]
        seller = people[20 + i % 6]
        prod = products[(i * 3) % len(products)]
        qty = rng.randrange(40, 400, 10)
        value = qty * rng.randrange(800, 2600, 50)
        month = (i % 5) + 1
        contracts.append({
            "id": f"eventos/contratos/2026-{month:02d}-acordo-{org['id'].rsplit('/', 1)[1]}",
            "org": org, "seller": seller, "prod": prod, "qty": qty, "value": value,
            "month": month, "month_name": month_names[month], "day": (i * 3) % 27 + 1,
        })

    incidents = []
    for i in range(5):
        prod = products[(i * 5 + 2) % len(products)]
        defect = DEFECTS[i % len(DEFECTS)]
        count = rng.randrange(7, 90)
        incidents.append({
            "id": f"eventos/recalls/2026-0{i % 4 + 2}-recall-{prod['name'].lower()}",
            "prod": prod, "defect": defect, "count": count, "lote": f"L{rng.randrange(10, 60)}-{chr(65 + i)}",
        })

    releases = []
    for i, proj in enumerate(projects):
        ver = f"{i + 1}.{rng.randrange(0, 9)}"
        feature = rng.choice(["suporte a rollback automático de firmware",
                              "compressão de payload em 6:1",
                              "provisionamento por QR code em campo",
                              "modo de baixo consumo com duty cycle adaptativo"])
        releases.append({"id": f"eventos/lancamentos/2026-04-versao-{proj['alias']}",
                         "proj": proj, "ver": ver, "feature": feature})

    return people, orgs, products, projects, contracts, incidents, releases


# ---------------------------------------------------------------------------
# Datasets (ground truth computed for questions)
# ---------------------------------------------------------------------------

def build_sales_db(path: Path, products) -> dict:
    """vendas/pedidos-2026.db — skewed so aggregates are unambiguous."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE pedidos (data TEXT, sku TEXT, produto TEXT, regiao TEXT, canal TEXT, qtd INTEGER, valor REAL)")
    weights = {"Norte": 0.6, "Nordeste": 2.6, "Centro-Oeste": 0.9, "Sudeste": 1.7, "Sul": 1.0}
    hot = products[4]  # Cangaço — boosted so the top-SKU answer is unambiguous
    rows, totals, sku_rev = [], {r: 0.0 for r in REGIONS}, {}
    for i in range(900):
        prod = products[i % len(products)]
        region = REGIONS[i % len(REGIONS)]
        month = (i % 6) + 1
        qtd = rng.randrange(1, 30)
        unit = rng.uniform(900, 2400) * weights[region] * (3.0 if prod is hot else 1.0)
        valor = round(qtd * unit, 2)
        rows.append((f"2026-{month:02d}-{(i % 27) + 1:02d}", prod["sku"], prod["name"], region,
                     rng.choice(CHANNELS), qtd, valor))
        totals[region] += valor
        sku_rev[prod["sku"]] = sku_rev.get(prod["sku"], 0.0) + valor
    conn.executemany("INSERT INTO pedidos VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    top_region = max(totals, key=totals.get)
    top_sku = max(sku_rev, key=sku_rev.get)
    return {"top_region": top_region, "top_region_total": totals[top_region],
            "top_sku": top_sku, "rows": len(rows)}


def build_support_db(path: Path, products) -> dict:
    """suporte/chamados-2026.db — ticket counts per product with causes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE chamados (aberto_em TEXT, produto TEXT, sku TEXT, causa TEXT, severidade TEXT, resolvido INTEGER)")
    champ = products[7]  # Caboclo — most tickets, unambiguous
    rows, counts = [], {}
    for i in range(420):
        prod = champ if i % 3 == 0 else products[i % len(products)]
        cause = DEFECTS[i % len(DEFECTS)]
        rows.append((f"2026-{(i % 5) + 1:02d}-{(i % 27) + 1:02d}", prod["name"], prod["sku"],
                     cause, rng.choice(["baixa", "média", "alta"]), rng.random() < 0.8))
        counts[prod["name"]] = counts.get(prod["name"], 0) + 1
    conn.executemany("INSERT INTO chamados VALUES (?,?,?,?,?,?)", rows)
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
        inst = f" Veio do {p['institute']}." if p["institute"] else ""
        node(p["id"], "entidade", p["name"],
             f"{p['role'].capitalize()} da Maracatu Sistemas. Mora em {p['city']} ({p['uf']}).{inst}",
             tags=["equipe"], links=[("relacionado-com", "organizacoes/maracatu-sistemas")],
             body=f"## Perfil\n\n{p['name']} é {p['role']} e vive em **{p['city']} ({p['uf']})**.{inst}\n\n## Atuação\n\nParticipa dos projetos da linha de telemetria da [[organizacoes/maracatu-sistemas]].",
             entity_kind="pessoa")

    node("organizacoes/maracatu-sistemas", "entidade", "Maracatu Sistemas",
         "Fabricante pernambucana de hardware e plataforma de telemetria industrial. Sede no Recife; linha de 18 produtos conectados.",
         tags=["empresa"], links=[],
         body="## Sobre\n\nFundada no Recife. Desenvolve sensores, gateways e a plataforma de telemetria.\n\n## Linha\n\nVer [[produtos/_index]].",
         entity_kind="organizacao")
    for o in orgs:
        node(o["id"], "entidade", o["name"],
             f"Cliente do segmento de {o['segment']}, baseado em {o['city']}. Compra equipamentos de telemetria da Maracatu Sistemas.",
             tags=["cliente", o["segment"].split()[0]],
             links=[("relacionado-com", "organizacoes/maracatu-sistemas")],
             body=f"## Sobre\n\n{o['name']} atua em {o['segment']} a partir de {o['city']}.\n\n## Relacionamento\n\nCliente ativo da [[organizacoes/maracatu-sistemas]].",
             entity_kind="organizacao")

    for pr in products:
        own = pr["owner"]
        node(pr["id"], "entidade", f"{pr['name']} ({pr['sku']})",
             f"{pr['desc'].capitalize()}, código de produto {pr['sku']}. Responsável técnico: {own['name']}.",
             tags=["produto"], links=[("relacionado-com", own["id"])],
             body=f"## Ficha\n\n**{pr['name']}** é uma {pr['desc']}. Código de catálogo: **{pr['sku']}**.\n\n## Responsável\n\nEngenharia sob cuidado de [[{own['id']}|{own['name']}]].",
             entity_kind="produto")

    for proj in projects:
        base, lead = proj["id_base"], proj["lead"]
        node(f"{base}/visao", "nota", f"Visão — {proj['alias']}",
             f"Norte do projeto {proj['alias']}: {proj['goal']}. Liderança de {lead['name']}.",
             tags=["projeto"], links=[("autor", lead["id"])],
             body=f"## Objetivo\n\nConstruir {proj['goal']}.\n\n## Liderança\n\nConduzido por [[{lead['id']}|{lead['name']}]].")
        node(f"{base}/arquitetura", "documento", f"Arquitetura — {proj['alias']}",
             f"Desenho técnico do {proj['alias']}: módulos, fluxo de dados e decisões de borda. Assinado por {lead['name']}.",
             tags=["projeto", "arquitetura"], links=[("autor", lead["id"]), ("parte-de", f"{base}/visao")],
             body=f"## Camadas\n\nIngestão → fila → processamento → API.\n\n## Autoria\n\nDesenho de [[{lead['id']}|{lead['name']}]], revisado pelo time.")
        node(f"{base}/decisoes", "nota", f"Decisões — {proj['alias']}",
             f"Registro de decisões do {proj['alias']}: trade-offs, alternativas descartadas e pendências.",
             tags=["projeto"], links=[("parte-de", f"{base}/visao")],
             body="## Decisões ativas\n\n- Banco embarcado na borda.\n- Telemetria comprimida.\n\n## Pendências\n\n- Estratégia de retry do backhaul.")

    redes = {"lpwan", "lorawan", "mqtt", "mesh", "nb-iot", "opc-ua", "scada",
             "duty-cycle", "backhaul", "payload-binario"}
    for c, t, d in CONCEPT_DEFS:
        sub = "redes" if c in redes else "operacao"
        node(f"conceitos/{sub}/{c}", "conceito", t, f"{d}.", tags=["conceito"],
             body=f"## Definição\n\n{d}.\n\n## Uso na Maracatu\n\nAparece nos produtos de telemetria e nos projetos da plataforma.")

    for ct in contracts:
        o, s, pr = ct["org"], ct["seller"], ct["prod"]
        node(ct["id"], "evento", f"Acordo {o['name']} — {ct['month_name']} de 2026",
             f"Contrato fechado em {ct['day']} de {ct['month_name']} de 2026 com {o['name']}: {ct['qty']} unidades de {pr['name']} ({pr['sku']}). Valor R$ {ct['value']:,.0f}. Vendedor: {s['name']}.".replace(",", "."),
             tags=["contrato"], links=[("relacionado-com", o["id"]), ("relacionado-com", pr["id"]), ("mencionado-em", s["id"])],
             body=f"## Termos\n\n{o['name']} adquiriu **{ct['qty']} unidades** do {pr['name']} (código {pr['sku']}) por **R$ {ct['value']:,.0f}**.".replace(",", ".") +
                  f"\n\n## Condução\n\nNegociação conduzida por [[{s['id']}|{s['name']}]] no canal direto.")

    for inc in incidents:
        pr = inc["prod"]
        node(inc["id"], "evento", f"Recall do {pr['name']} — lote {inc['lote']}",
             f"Recall de {inc['count']} unidades do {pr['name']} ({pr['sku']}) por {inc['defect']}, lote {inc['lote']}. Substituição sem custo em 30 dias.",
             tags=["recall", "qualidade"], links=[("relacionado-com", pr["id"])],
             body=f"## O que houve\n\n**{inc['count']} unidades** do {pr['name']} apresentaram **{inc['defect']}** (lote {inc['lote']}).\n\n## Ação\n\nSubstituição integral; causa raiz na linha de montagem.")

    for rel in releases:
        proj = rel["proj"]
        node(rel["id"], "evento", f"Versão {rel['ver']} — {proj['alias']}",
             f"Lançamento de abril de 2026 do {proj['alias']}: versão {rel['ver']} com {rel['feature']}.",
             tags=["release"], links=[("relacionado-com", f"{proj['id_base']}/visao")],
             body=f"## Novidades\n\nA versão **{rel['ver']}** trouxe {rel['feature']}.\n\n## Contexto\n\nMarco do [[{proj['id_base']}/visao|{proj['alias']}]].")

    node("vendas/pedidos-2026", "dataset", "Pedidos 2026 (jan-jun)",
         f"Pedidos faturados de janeiro a junho de 2026: {sales_truth['rows']} linhas com sku, produto, região, canal, quantidade e valor em BRL. Export do ERP.",
         tags=["vendas", "dataset"], links=[],
         body="## Manual de consulta\n\n**Tabela:** `pedidos(data, sku, produto, regiao, canal, qtd, valor)`\n\n**Queries de exemplo:**\n- Faturamento por região: `SELECT regiao, SUM(valor) AS total FROM pedidos GROUP BY regiao ORDER BY total DESC`\n- Receita por produto: `SELECT sku, produto, SUM(valor) AS receita FROM pedidos GROUP BY sku ORDER BY receita DESC`",
         payload="pedidos-2026.db", payload_type="sqlite")
    node("suporte/chamados-2026", "dataset", "Chamados de suporte 2026",
         f"Tíquetes de suporte de 2026: {support_truth['rows']} linhas com produto, sku, causa, severidade e status de resolução.",
         tags=["suporte", "dataset"], links=[],
         body="## Manual de consulta\n\n**Tabela:** `chamados(aberto_em, produto, sku, causa, severidade, resolvido)`\n\n**Queries de exemplo:**\n- Chamados por produto: `SELECT produto, COUNT(*) AS n FROM chamados GROUP BY produto ORDER BY n DESC`\n- Causas mais comuns: `SELECT causa, COUNT(*) FROM chamados GROUP BY causa ORDER BY 2 DESC`",
         payload="chamados-2026.db", payload_type="sqlite")

    node("notas/politica-garantia", "nota", "Política de garantia",
         "Garantia padrão de 24 meses para sensores e 36 para gateways; recall sempre com substituição sem custo. Exceções só com aprovação da diretoria.",
         tags=["politica"], body="## Regra\n\n24 meses (sensores), 36 meses (gateways).\n\n## Recalls\n\nSubstituição sem custo, prazo de 30 dias.")
    node("notas/onboarding-clientes", "nota", "Onboarding de clientes",
         "Passo a passo de ativação de um cliente novo: provisionamento dos dispositivos, treinamento e primeira semana assistida.",
         tags=["processo"], body="## Etapas\n\n1. Provisionamento ([[conceitos/operacao/provisionamento]])\n2. Treinamento\n3. Semana assistida")
    node("infra/bancada-homologacao", "nota", "Bancada de homologação",
         "Bancada de testes de rádio e clima: câmara térmica, atenuadores e gateways de referência das classes A e C.",
         tags=["infra"], body="## Equipamentos\n\nCâmara térmica, atenuadores RF, gateways de referência.\n\n## Uso\n\nHomologação de firmware antes do OTA ([[conceitos/operacao/ota-update]]).")


BRANCH_DEFS = {
    "pessoas/_index": ("Pessoas", "Equipe da Maracatu Sistemas por área: engenharia, dados e comercial."),
    "pessoas/engenharia/_index": ("Engenharia", "Time de firmware, software embarcado, confiabilidade e qualidade."),
    "pessoas/dados/_index": ("Dados e IA", "Time de dados, ciência de dados, IA e telemetria."),
    "pessoas/comercial/_index": ("Comercial", "Gerentes de contas que conduzem vendas e contratos."),
    "organizacoes/_index": ("Organizações", "A própria Maracatu e os clientes, agrupados por perfil."),
    "organizacoes/clientes-campo/_index": ("Clientes de campo", "Clientes de agro, cooperativas, energia e pesca."),
    "organizacoes/clientes-industria/_index": ("Clientes industriais", "Clientes de logística, mineração, saúde e manufatura."),
    "produtos/_index": ("Produtos", "Linha de hardware conectado, agrupada por ambiente de uso."),
    "produtos/campo/_index": ("Produtos de campo", "Sensores e kits para fazendas, água e clima."),
    "produtos/industria/_index": ("Produtos industriais", "Sensores e painéis para planta industrial."),
    "produtos/logistica/_index": ("Produtos de logística", "Rastreadores, leitores e balanças de expedição."),
    "projetos/_index": ("Projetos", "Iniciativas internas: visão, arquitetura e decisões de cada projeto."),
    "conceitos/_index": ("Conceitos", "Vocabulário técnico, dividido em redes e operações."),
    "conceitos/redes/_index": ("Redes", "Protocolos e rádio: LPWAN, LoRaWAN, MQTT, mesh, backhaul."),
    "conceitos/operacao/_index": ("Operação", "Operações: OTA, manutenção preditiva, cadeia fria, provisionamento."),
    "eventos/_index": ("Eventos", "Fatos datados, agrupados em contratos, recalls e lançamentos."),
    "eventos/contratos/_index": ("Contratos", "Acordos comerciais fechados com clientes: quantidades, valores e vendedores."),
    "eventos/recalls/_index": ("Recalls", "Recolhimentos por defeito de fabricação: produto, lote e causa."),
    "eventos/lancamentos/_index": ("Lançamentos", "Versões lançadas dos projetos com as novidades principais."),
    "vendas/_index": ("Vendas", "Datasets de pedidos faturados com manual de consulta SQL."),
    "suporte/_index": ("Suporte", "Datasets de chamados com causas e severidade."),
    "infra/_index": ("Infra", "Bancadas e ambientes de homologação."),
    "notas/_index": ("Notas", "Políticas e processos internos."),
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
        branches[f"{nested_dir}/_index"] = (alias, f"Materiais do projeto {alias}: visão, arquitetura e decisões.")

    def children_of(branch_id):
        folder = branch_id[: -len("/_index")]
        subs = [b for b in branches if b != branch_id and b[: -len("/_index")].rsplit("/", 1)[0] == folder]
        bananas = [nid for nid in sorted(by_id) if nid.rsplit("/", 1)[0] == folder]
        return sorted(subs), bananas

    for branch_id, (title, blurb) in branches.items():
        subs, bananas = children_of(branch_id)
        lines = [f"# {title}", "", f"> {blurb}", ""]
        if subs:
            lines.append("## Sub-galhos")
            lines += [entry_line(s, branches[s][1]) for s in subs]
            lines.append("")
        lines.append("## Bananas diretas")
        lines += [entry_line(b, by_id[b]["summary"]) for b in bananas]
        lines.append("")
        body = "\n".join(lines)
        fm = {"id": branch_id, "type": "galho", "title": title, "summary": blurb,
              "coverage": count_coverage(body), "created": CREATED, "updated": TODAY}
        path = out / f"{branch_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    top = sorted(b for b in branches if b.count("/") == 1)
    lines = ["# Floresta Maracatu", "",
             "> Base de conhecimento da Maracatu Sistemas: equipe, clientes, linha de produtos, "
             "projetos, conceitos de telemetria, contratos, recalls, vendas e suporte.", "",
             "## Sub-galhos"]
    lines += [entry_line(b, branches[b][1]) for b in top]
    lines += ["", "## Bananas diretas", ""]
    body = "\n".join(lines)
    fm = {"id": "_index", "type": "galho", "title": "Floresta Maracatu",
          "summary": "Galho-mestre da Maracatu Sistemas: pessoas, organizações, produtos, projetos, conceitos, eventos, vendas, suporte, infra e notas.",
          "coverage": count_coverage(body), "created": CREATED, "updated": TODAY}
    (out / "_index.md").write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")
    return len(N) + len(branches) + 1


# ---------------------------------------------------------------------------
# Questions v2 — paraphrase templates with vocabulary disjoint from summaries
# ---------------------------------------------------------------------------

def build_questions(people, products, projects, contracts, incidents, releases,
                    sales_truth, support_truth) -> list[dict]:
    qs = []

    def q(qid, question, expected, contains):
        qs.append({"id": qid, "question": question,
                   "expected_nodes": expected, "answer_contains": contains})

    # author-of-project -> city (summaries say "Liderança/Mora em"; questions say "à frente / reside")
    for i, proj in enumerate(projects[:3]):
        lead = proj["lead"]
        q(f"q{len(qs)+1:02d}",
          f"Quem está à frente do {proj['alias']} e em que município essa pessoa reside?",
          [f"{proj['id_base']}/visao", lead["id"]],
          [lead["first"], lead["city"]])

    # contracts (summaries: "Contrato fechado... Vendedor:"; questions: "negócio/quem cuidou")
    for ct in contracts[:3]:
        q(f"q{len(qs)+1:02d}",
          f"Em {ct['month_name']} de 2026 a {ct['org']['name']} levou qual equipamento, em que quantidade, e quem cuidou da venda?",
          [ct["id"]],
          [ct["prod"]["name"], str(ct["qty"]), ct["seller"]["first"]])

    # recalls (summaries: "Recall de N unidades por <defeito>"; questions: "devolvidas/problema")
    for inc in incidents[:2]:
        q(f"q{len(qs)+1:02d}",
          f"O {inc['prod']['name']} teve um problema de fabricação em 2026: quantas peças voltaram e qual era o defeito?",
          [inc["id"]],
          [str(inc["count"]), inc["defect"].split()[0]])

    # releases
    for rel in releases[:2]:
        q(f"q{len(qs)+1:02d}",
          f"O lançamento de abril do {rel['proj']['alias']} saiu com qual número de versão e qual novidade principal?",
          [rel["id"]],
          [rel["ver"]])

    # dataset aggregates (need SQL)
    q(f"q{len(qs)+1:02d}",
      "Considerando tudo que foi faturado no primeiro semestre de 2026, qual área do país ficou na liderança?",
      ["vendas/pedidos-2026"],
      [sales_truth["top_region"]])
    q(f"q{len(qs)+1:02d}",
      "Qual código de produto puxou a maior receita no semestre, segundo a base de pedidos?",
      ["vendas/pedidos-2026"],
      [sales_truth["top_sku"]])
    q(f"q{len(qs)+1:02d}",
      "Qual item da linha gerou o maior volume de tíquetes de atendimento em 2026?",
      ["suporte/chamados-2026"],
      [support_truth["top_product"]])

    # product SKU lookups (summaries: "código de produto"; questions: "referência de catálogo")
    for pr in (products[2], products[9]):
        q(f"q{len(qs)+1:02d}",
          f"Qual é a referência de catálogo do {pr['name']} e quem responde tecnicamente por ele?",
          [pr["id"]],
          [pr["sku"], pr["owner"]["first"]])

    # person origin institute
    cands = [p for p in people if p["institute"]]
    for p in cands[:2]:
        q(f"q{len(qs)+1:02d}",
          f"De qual instituição {p['name']} veio antes da Maracatu, e qual é a função dela(e) hoje?",
          [p["id"]],
          [p["institute"].split()[-1]])

    # policy multi-hop (note)
    q(f"q{len(qs)+1:02d}",
      "Quando um lote inteiro dá defeito, o que a política da empresa garante ao cliente e em qual prazo?",
      ["notas/politica-garantia"],
      ["30"])

    return qs


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench-forest")
    ap.add_argument("--questions-out", default=str(REPO / "bench" / "questions-v2.json"))
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
    sales_truth = build_sales_db(out / "vendas" / "pedidos-2026.db", products)
    support_truth = build_support_db(out / "suporte" / "chamados-2026.db", products)
    populate(people, orgs, products, projects, contracts, incidents, releases,
             sales_truth, support_truth)
    total = write_forest(out)

    questions = build_questions(people, products, projects, contracts, incidents,
                                releases, sales_truth, support_truth)
    Path(args.questions_out).write_text(
        json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")

    def git(*a):
        subprocess.run(["git", "-C", str(out), "-c", "user.name=bench", "-c",
                        "user.email=bench@monkeyllm.local", *a],
                       check=True, capture_output=True, text=True)
    git("init", "--quiet")
    (out / ".gitignore").write_text("_derived/\n.vine.lock\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "--quiet", "-m", f"bench forest: {total} nodes, 2 datasets")

    print(f"bench forest: {total} nodes em {out}")
    print(f"ground truth vendas: top região={sales_truth['top_region']}, top SKU={sales_truth['top_sku']}")
    print(f"ground truth suporte: campeão de chamados={support_truth['top_product']} ({support_truth['top_count']})")
    print(f"{len(questions)} perguntas em {args.questions_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
