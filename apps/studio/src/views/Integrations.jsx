// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Integrations (J.5): the deployment and integration manual, inside the
 * deployment it describes.
 *
 * A console rather than a static site on purpose: every example below
 * carries this Station's own origin, so each snippet is copy-ready for the
 * host the administrator is actually looking at — documentation that cannot
 * drift from the deployment it documents. Admin-gated like People and
 * Audit: it describes credentials, hosts and the container, which is the
 * administrator's vocabulary, not the reader's.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n.jsx'
import { Badge, Card, CopyButton, Note, Table, Td } from '../design/ui.jsx'
import { Highlighted } from '../design/highlight.jsx'
import {
  Copy, Download, File, Key, Link, Monitor, Playground, Plug,
} from '../design/icons.jsx'
import { ALL_CAPS, NeedsCapability, has } from './shared.jsx'

const SECTIONS = ['overview', 'install', 'deploy', 'mcp', 'api', 'clipper', 'access', 'env']

const SECTION_ICON = {
  overview: Link, install: Download, deploy: Monitor, mcp: Plug,
  api: Playground, clipper: Copy, access: Key, env: File,
}

/** Tool name → the capability it needs (null = any valid key). */
const MCP_TOOLS = [
  ['forests', null], ['locate', 'read'], ['look', 'read'], ['move', 'read'],
  ['pick', 'read'], ['scan', 'read'], ['sniff', 'read'], ['harvest', 'read'],
  ['answer', 'read'], ['view', 'read'], ['query', 'query'], ['plant', 'write'],
  ['graft', 'write'], ['tend', 'tend'], ['ingest', 'ingest'],
]

/** Route → who may call it → the description key. */
const ROUTES = [
  ['GET /v1/health', 'none', 'health'],
  ['POST /v1/auth/login', 'none', 'login'],
  ['POST /v1/auth/pair', 'none', 'pair'],
  ['GET /v1/me', 'key', 'me'],
  ['GET /v1/forests', 'key', 'forests'],
  ['POST /v1/forests/{forest}/{name}', 'cap', 'call'],
  ['GET /v1/forests/{forest}/payload/{node}', 'read', 'payload'],
  ['POST /v1/admin/forests', 'admin', 'admin_forests'],
  ['GET, POST /v1/admin/people', 'admin', 'people'],
  ['GET, POST /v1/admin/keys', 'admin', 'keys'],
  ['POST /v1/admin/grant', 'admin', 'grant'],
  ['POST /v1/admin/password', 'admin', 'password'],
  ['GET /v1/admin/audit', 'admin', 'audit'],
  ['GET, POST /v1/admin/providers', 'admin', 'providers'],
  ['GET, POST /v1/admin/models', 'admin', 'models'],
  ['GET, POST /v1/admin/canopy', 'admin', 'canopy'],
]

const NEED_TONE = { read: 'accent', cap: 'accent', admin: 'warn' }

const ENV_VARS = [
  [['MONKEYLLM_STATION_ADMIN', 'MONKEYLLM_STATION_PASSWORD'], 'admin'],
  [['MONKEYLLM_STATION_ALLOWED_HOSTS'], 'hosts'],
  [['STATION_PORT'], 'port'],
  [['MONKEYLLM_LLM_ENDPOINT', 'MONKEYLLM_LLM_API_KEY', 'MONKEYLLM_LLM_PROVIDER'], 'llm'],
  [['MONKEYLLM_LLM_MODEL', 'MONKEYLLM_LLM_MAX_TOKENS', 'MONKEYLLM_LLM_REASONING'], 'llm_model'],
  [['MONKEYLLM_EMBED_ENDPOINT', 'MONKEYLLM_EMBED_MODEL', 'MONKEYLLM_EMBED_API_KEY'], 'embed'],
  [['MONKEYLLM_S3_ENDPOINT'], 's3'],
  [['MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE'], 'provider_private'],
  [['MONKEYLLM_STATION_IMPORT_MAX_MB'], 'import_max_mb'],
]

/** Which section the reader is in, so the page nav can say so. The first
 *  visible section wins in document order — matching what a reader calls
 *  "where I am" when two sections share the viewport. */
function useActiveSection() {
  const [active, setActive] = useState(SECTIONS[0])
  useEffect(() => {
    const visible = new Set()
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) visible.add(e.target.dataset.section)
        else visible.delete(e.target.dataset.section)
      }
      const first = SECTIONS.find((id) => visible.has(id))
      if (first) setActive(first)
    }, { rootMargin: '-10% 0px -60% 0px' })
    for (const id of SECTIONS) {
      const el = document.getElementById(`doc-${id}`)
      if (el) io.observe(el)
    }
    return () => io.disconnect()
  }, [])
  return active
}

const P = ({ children }) => (
  <p className="max-w-[72ch] text-[13px] leading-relaxed text-text-2">{children}</p>
)

const H = ({ children }) => (
  <h3 className="pt-1.5 text-[13px] font-semibold text-text">{children}</h3>
)

const Mono = ({ children }) => (
  <code className="rounded bg-surface-2 px-1 py-px font-mono text-[12px] text-text">
    {children}
  </code>
)

/** `lang` defaults to the title because most blocks here are titled with the
 *  language they hold; the ones titled with a translated sentence name it. */
function CodeBlock({ title, code, lang = title }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface-2">
      <div className="flex items-center justify-between gap-3 border-b border-line
                      py-1 pl-3 pr-1.5">
        <span className="truncate font-mono text-[11px] text-text-3">{title}</span>
        <CopyButton value={code} />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[12px] leading-relaxed
                      text-text-2">
        <Highlighted text={code} lang={lang} />
      </pre>
    </div>
  )
}

function Section({ id, title, sub, children }) {
  return (
    <section id={`doc-${id}`} data-section={id} className="scroll-mt-16 lg:scroll-mt-6">
      <Card title={title} subtitle={sub} icon={SECTION_ICON[id]}
            bodyClass="space-y-4 p-5">
        {children}
      </Card>
    </section>
  )
}

export default function Integrations({ grant }) {
  const { t } = useI18n()
  const active = useActiveSection()
  const admin = has(grant, 'admin')

  if (!admin) {
    return <NeedsCapability message={t('integrations.locked')}
                            hint={t('cap.admin')} />
  }

  const origin = window.location.origin
  const go = (id) => document.getElementById(`doc-${id}`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  return (
    <div className="lg:flex lg:items-start lg:gap-8">
      {/* The page's own nav, like any manual worth reading: sections are
          long, and "where am I" should not require scrolling to find out. */}
      <nav className="sticky top-6 hidden w-[190px] shrink-0 lg:block">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em]
                      text-text-3">
          {t('integrations.on_page')}
        </p>
        <ul className="space-y-0.5 border-l border-line">
          {SECTIONS.map((id) => (
            <li key={id}>
              <button onClick={() => go(id)} aria-current={active === id ? 'true' : undefined}
                      className={`-ml-px block w-full border-l-2 py-1 pl-3 pr-2 text-left
                                  text-[12.5px] transition
                                  ${active === id
                                    ? 'border-accent font-medium text-accent'
                                    : 'border-transparent text-text-3 hover:text-text-2'}`}>
                {t(`integrations.${id}.title`)}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 flex-1 space-y-5">
        <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 lg:hidden">
          {SECTIONS.map((id) => (
            <button key={id} onClick={() => go(id)}
                    className={`badge whitespace-nowrap ${active === id ? 'badge-accent' : ''}`}>
              {t(`integrations.${id}.title`)}
            </button>
          ))}
        </div>

        <Section id="overview" title={t('integrations.overview.title')}
                 sub={t('integrations.overview.sub')}>
          <P>{t('integrations.overview.p1')}</P>
          <Table head={[t('integrations.surface'), t('integrations.surface_for'),
                        t('integrations.surface_where')]}>
            <tr>
              <Td className="font-medium text-text">Studio</Td>
              <Td>{t('integrations.surface_studio')}</Td>
              <Td className="whitespace-nowrap font-mono text-[11.5px] text-text-3">{origin}/</Td>
            </tr>
            <tr>
              <Td className="font-medium text-text">REST</Td>
              <Td>{t('integrations.surface_rest')}</Td>
              <Td className="whitespace-nowrap font-mono text-[11.5px] text-text-3">{origin}/v1/…</Td>
            </tr>
            <tr>
              <Td className="font-medium text-text">MCP</Td>
              <Td>{t('integrations.surface_mcp')}</Td>
              <Td className="whitespace-nowrap font-mono text-[11.5px] text-text-3">{origin}/mcp/</Td>
            </tr>
          </Table>
          <P>{t('integrations.overview.p2')}</P>
        </Section>

        <Section id="install" title={t('integrations.install.title')}
                 sub={t('integrations.install.sub')}>
          <H>{t('integrations.install.docker')}</H>
          <P>{t('integrations.install.docker_p')}</P>
          <CodeBlock title="bash" code={`cp .env.example .env
docker compose up --build -d
docker compose logs station | grep "API key"`} />
          <Note tone="warn">{t('integrations.install.bootstrap')}</Note>
          <H>{t('integrations.install.source')}</H>
          <P>{t('integrations.install.source_p')}</P>
          <CodeBlock title="bash" code={`pip install -e . && pip install -e apps/station
(cd apps/studio && npm ci && npm run build)
station serve --root forests --registry ./station.db --port 8800 --writable`} />
          <H>{t('integrations.install.first')}</H>
          <P>{t('integrations.install.first_p')}</P>
          <CodeBlock title="bash" code={`docker compose exec station vine init --forest /forests/handbook --title "Handbook"
docker compose exec station station key --principal admin --forest handbook \\
  --caps read,query,write,tend,ingest,admin`} />
        </Section>

        <Section id="deploy" title={t('integrations.deploy.title')}
                 sub={t('integrations.deploy.sub')}>
          <P>{t('integrations.deploy.volumes_p')}</P>
          <Table head={[t('integrations.deploy.volume'), t('integrations.deploy.mount'),
                        t('integrations.deploy.holds')]}>
            {[['forests', '/forests', 'vol_forests'],
              ['registry', '/registry', 'vol_registry'],
              ['models', '/models', 'vol_models']].map(([name, mount, key]) => (
              <tr key={name}>
                <Td className="font-mono text-[12px] text-text">{name}</Td>
                <Td className="whitespace-nowrap font-mono text-[11.5px] text-text-3">{mount}</Td>
                <Td>{t(`integrations.deploy.${key}`)}</Td>
              </tr>
            ))}
          </Table>
          <H>{t('integrations.deploy.dokploy')}</H>
          <ol className="max-w-[72ch] list-decimal space-y-1.5 pl-5 text-[13px]
                         leading-relaxed text-text-2">
            {[1, 2, 3, 4, 5].map((n) => <li key={n}>{t(`integrations.deploy.dok${n}`)}</li>)}
          </ol>
          <H>{t('integrations.deploy.local_llm')}</H>
          <P>{t('integrations.deploy.local_llm_p')}</P>
          <CodeBlock title="bash" code={`docker compose --profile local-llm --profile local-embed up -d

# .env — point the Station at the sidecars:
MONKEYLLM_LLM_ENDPOINT=http://llm:8090/v1
MONKEYLLM_EMBED_ENDPOINT=http://embed:8091/v1`} />
          <H>{t('integrations.deploy.updates')}</H>
          <P>{t('integrations.deploy.updates_p')}</P>
          <CodeBlock title="bash" code={`docker compose exec station vine snapshot create --forest /forests/handbook`} />
          <Note>{t('integrations.deploy.readonly')}</Note>
        </Section>

        <Section id="mcp" title={t('integrations.mcp.title')}
                 sub={t('integrations.mcp.sub')}>
          <P>{t('integrations.mcp.p1')}</P>
          <CodeBlock title={t('integrations.mcp.endpoint')} lang="bash"
                     code={`${origin}/mcp/
Authorization: Bearer mk_…`} />
          <Note>{t('integrations.mcp.first_call')}</Note>
          <H>{t('integrations.mcp.client_claude')}</H>
          <CodeBlock title="bash" code={`claude mcp add --transport http monkeyllm ${origin}/mcp/ \\
  --header "Authorization: Bearer $MONKEYLLM_KEY"`} />
          <H>{t('integrations.mcp.client_json')}</H>
          <CodeBlock title="json" code={`{
  "mcpServers": {
    "monkeyllm": {
      "type": "http",
      "url": "${origin}/mcp/",
      "headers": { "Authorization": "Bearer mk_…" }
    }
  }
}`} />
          <H>{t('integrations.mcp.client_http')}</H>
          <CodeBlock title="bash" code={`curl -sX POST ${origin}/mcp/ \\
  -H "Authorization: Bearer $KEY" \\
  -H 'content-type: application/json' \\
  -H 'accept: application/json, text/event-stream' \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`} />
          <Note tone="warn">{t('integrations.mcp.hosts')}</Note>
          <H>{t('integrations.mcp.tools')}</H>
          <Table head={[t('integrations.mcp.tool'), t('integrations.mcp.needs'),
                        t('integrations.mcp.does')]}>
            {MCP_TOOLS.map(([name, cap]) => (
              <tr key={name}>
                <Td className="font-mono text-[12px] text-text">{name}</Td>
                <Td>
                  <Badge tone={cap ? 'accent' : undefined}>
                    {cap || t('integrations.needs_key')}
                  </Badge>
                </Td>
                <Td>{t(`integrations.tool.${name}`)}</Td>
              </tr>
            ))}
          </Table>
        </Section>

        <Section id="api" title={t('integrations.api.title')}
                 sub={t('integrations.api.sub')}>
          <H>{t('integrations.api.auth')}</H>
          <P>{t('integrations.api.auth_p')}</P>
          <CodeBlock title="bash" code={`curl -sX POST ${origin}/v1/auth/login \\
  -H 'content-type: application/json' \\
  -d '{"username": "admin", "password": "…"}'`} />
          <H>{t('integrations.api.pattern')}</H>
          <P>{t('integrations.api.pattern_p')}</P>
          <CodeBlock title={t('integrations.api.ex_answer')} lang="bash"
                     code={`curl -sX POST ${origin}/v1/forests/handbook/answer \\
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \\
  -d '{"question": "what is our expense policy?"}'`} />
          <CodeBlock title={t('integrations.api.ex_harvest')} lang="bash"
                     code={`curl -sX POST ${origin}/v1/forests/handbook/harvest \\
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \\
  -d '{"query": "expense policy", "terms": ["receipt"], "k": 3}'`} />
          <CodeBlock title={t('integrations.api.ex_ingest')} lang="bash"
                     code={`curl -sX POST ${origin}/v1/forests/handbook/ingest \\
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \\
  -d '{"mode": "upload", "dest": "policies",
       "files": [{"name": "expenses.md", "text": "# Expenses…"}]}'`} />
          <H>{t('integrations.api.errors')}</H>
          <P>{t('integrations.api.errors_p')}</P>
          <CodeBlock title="json" code={`{
  "error": {
    "code": "E_FORBIDDEN",
    "message": "missing or invalid API key",
    "hint": "Send Authorization: Bearer <key>."
  }
}`} />
          <H>{t('integrations.api.routes')}</H>
          <Table head={[t('integrations.api.route'), t('integrations.mcp.needs'),
                        t('integrations.mcp.does')]}>
            {ROUTES.map(([route, need, key]) => (
              <tr key={route}>
                <Td className="whitespace-nowrap font-mono text-[11.5px] text-text">{route}</Td>
                <Td>
                  <Badge tone={NEED_TONE[need]}>{t(`integrations.needs_${need}`)}</Badge>
                </Td>
                <Td>{t(`integrations.route.${key}`)}</Td>
              </tr>
            ))}
          </Table>
        </Section>

        {/* The Clipper (J.15) is a client like the two sections above it —
            MCP for agents, REST for scripts, this for the browser — and its
            credential story is the bridge into the access section below:
            pairing (J.2.6) mints a key that can only narrow, never add. The
            origin rendered here is this Station's own, like every snippet on
            this page: the extension asks for exactly that string. */}
        <Section id="clipper" title={t('integrations.clipper.title')}
                 sub={t('integrations.clipper.sub')}>
          <P>{t('integrations.clipper.p1')}</P>
          <H>{t('integrations.clipper.install')}</H>
          <ol className="max-w-[72ch] list-decimal space-y-1.5 pl-5 text-[13px]
                         leading-relaxed text-text-2">
            {[1, 2, 3].map((n) => (
              <li key={n}>{t(`integrations.clipper.in${n}`, { origin })}</li>
            ))}
          </ol>
          <H>{t('integrations.clipper.pair')}</H>
          <P>{t('integrations.clipper.pair_p1')}</P>
          <CodeBlock title={t('integrations.clipper.origin')} lang="bash" code={origin} />
          <P>{t('integrations.clipper.pair_p2')}</P>
          <CodeBlock title={t('integrations.clipper.ex_pair')} lang="bash"
                     code={`curl -sX POST ${origin}/v1/auth/pair \\
  -H 'content-type: application/json' \\
  -d '{"username": "you", "password": "…", "label": "clipper-laptop"}'`} />
          <Note>{t('integrations.clipper.revoke')}</Note>
        </Section>

        <Section id="access" title={t('integrations.access.title')}
                 sub={t('integrations.access.sub')}>
          <P>{t('integrations.access.p1')}</P>
          <H>{t('integrations.access.caps')}</H>
          <ul className="max-w-[72ch] space-y-1.5 text-[13px] leading-relaxed text-text-2">
            {ALL_CAPS.map((c) => (
              <li key={c} className="flex items-baseline gap-2.5">
                <Mono>{c}</Mono>
                <span>{t(`cap.${c}`)}</span>
              </li>
            ))}
          </ul>
          <P>{t('integrations.access.roles')}</P>
          <H>{t('integrations.access.keys')}</H>
          <P>{t('integrations.access.keys_p')}</P>
          <H>{t('integrations.access.breakglass')}</H>
          <P>{t('integrations.access.breakglass_p')}</P>
          <CodeBlock title=".env" code={`MONKEYLLM_STATION_ADMIN=jimmy
MONKEYLLM_STATION_PASSWORD=something long and unguessable`} />
          <H>{t('integrations.access.audit')}</H>
          <P>{t('integrations.access.audit_p')}</P>
        </Section>

        <Section id="env" title={t('integrations.env.title')}
                 sub={t('integrations.env.sub')}>
          <Table head={[t('integrations.env.var'), t('integrations.env.what')]}>
            {ENV_VARS.map(([vars, key]) => (
              <tr key={key}>
                <Td className="font-mono text-[11px] text-text">
                  {vars.map((v) => <div key={v} className="whitespace-nowrap">{v}</div>)}
                </Td>
                <Td>{t(`integrations.env.${key}`)}</Td>
              </tr>
            ))}
          </Table>
        </Section>
      </div>
    </div>
  )
}
