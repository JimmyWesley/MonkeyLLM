import { useMemo, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, CheckList, Code, CopyButton, Empty, ErrorNote, Field, Modal,
  Note, Select, Skeleton, Spinner, Table, Tabs, Td, Toggle,
} from '../design/ui.jsx'
import { Access as Shield, Key, Plus, Trash, Users } from '../design/icons.jsx'
import {
  ALL_CAPS, NeedsCapability, branchOf, has, useAsync, useForestTree,
} from './shared.jsx'

/** Governance, shaped like a person (spec J.5.5).
 *
 * The previous version had three screens — grants here, tokens there,
 * passwords in a third — which is the storage model wearing a navigation
 * bar. Nobody administers a *grant*; they onboard somebody, and that is one
 * thought: who they are, what they may see, how they sign in, and a token
 * for their scripts. So it is one form, and afterwards one row that owns
 * every change to that person.
 */
const ROLES = {
  reader: ['read'],
  analyst: ['read', 'query'],
  editor: ['read', 'query', 'write', 'tend'],
  curator: ['read', 'query', 'write', 'tend', 'ingest'],
  owner: ALL_CAPS,
}

const LIFETIMES = [7, 30, 90, 365]

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x))
export const roleOf = (caps = []) =>
  Object.keys(ROLES).find((r) => sameSet(ROLES[r], caps)) || 'custom'

/** Whether every forest this person holds carries the same level. */
const levelled = (grants = []) =>
  grants.length > 0 && grants.every((g) => sameSet(g.caps || [], grants[0].caps || []))

/** …the same level *and* the same scope, so it can be stated once. */
const uniform = (grants = []) =>
  levelled(grants) && grants.every((g) =>
    (g.allow || []).join() === (grants[0].allow || []).join()
    && (g.deny || []).join() === (grants[0].deny || []).join())

export default function People({ forest, grant, me }) {
  const { t } = useI18n()
  const [tab, setTab] = useState('people')
  const [editing, setEditing] = useState(null)   // principal id or '' for new
  const [secret, setSecret] = useState(null)

  const admin = has(grant, 'admin')
  const data = useAsync(() => api.people(), [], { skip: !admin })

  if (!admin) {
    return <NeedsCapability message={t('people.needs_admin')}
                            hint={t('people.needs_admin_hint')} />
  }

  const people = data.data?.people || []
  const forests = data.data?.forests || []
  const person = editing ? people.find((p) => p.id === editing) : null

  return (
    <div className="space-y-4">
      <Card
        title={tab === 'people' ? t('people.title') : t('tokens.title')}
        subtitle={tab === 'people' ? t('people.sub') : t('tokens.sub')}
        icon={tab === 'people' ? Users : Key}
        actions={<button className="btn btn-primary btn-sm" onClick={() => setEditing('')}>
          <Plus size={14} /> {t('people.new')}
        </button>}
        bodyClass="p-0">
        <div className="px-5 pt-3">
          <Tabs value={tab} onChange={setTab} options={[
            { value: 'people', label: t('people.tab_people') },
            { value: 'tokens', label: t('people.tab_tokens') },
          ]} />
        </div>
        <div className="p-5">
          {data.busy ? <Skeleton rows={4} />
            : data.error ? <ErrorNote error={data.error} onRetry={data.reload} />
            : tab === 'people'
              ? <PeopleTable people={people} me={me} onOpen={setEditing} />
              : <TokenTable people={people} onChanged={data.reload}
                            onError={() => {}} />}
        </div>
      </Card>

      <Levels />

      {editing !== null && (
        <PersonDrawer
          person={person} forests={forests} me={me} defaultForest={forest}
          onClose={() => setEditing(null)}
          onSaved={(res) => {
            data.reload()
            if (res?.api_key) setSecret({ who: res.principal, key: res.api_key })
            setEditing(null)
          }} />
      )}

      <Modal open={Boolean(secret)} onClose={() => setSecret(null)}
             title={t('tokens.issued_for', { who: secret?.who })}
             subtitle={t('tokens.once')}
             footer={<>
               <CopyButton value={secret?.key} label={t('common.copy')} />
               <button className="btn btn-primary" onClick={() => setSecret(null)}>
                 {t('common.close')}
               </button>
             </>}>
        <Code max="8rem">{secret?.key}</Code>
      </Modal>
    </div>
  )
}

function PeopleTable({ people, me, onOpen }) {
  const { t } = useI18n()
  if (people.length === 0) {
    return <Empty icon={Users} title={t('people.none')}>{t('people.none_hint')}</Empty>
  }
  return (
    <Table head={[t('access.who'), t('access.role'), t('access.scope'),
                  t('people.signin'), t('people.tokens'), t('people.last_seen'), '']}>
      {people.map((p) => (
        <tr key={p.id}>
          <Td>
            <span className="flex items-center gap-2">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full
                               bg-accent-soft text-[10px] font-semibold uppercase text-accent">
                {p.id.slice(0, 2)}
              </span>
              <span className="font-medium text-text">{p.id}</span>
              {p.id === me.principal && <Badge>{t('people.you')}</Badge>}
            </span>
          </Td>
          <Td>
            {/* One level over several forests is the common case, so it is
                shown once with a count rather than as N identical badges —
                and the count names them on hover, because "9 forests" that
                cannot be expanded is a number, not an answer. */}
            {uniform(p.grants) ? (
              <span className="flex flex-wrap items-center gap-1">
                <Badge tone="accent">{t(`role.${roleOf(p.grants[0].caps)}`)}</Badge>
                <ForestsBadge grants={p.grants} />
              </span>
            ) : (
              <div className="space-y-1">
                {p.grants.map((g) => (
                  <div key={g.forest} className="flex min-h-[19px] items-center gap-1">
                    <Badge tone="accent">{t(`role.${roleOf(g.caps)}`)}</Badge>
                    <Badge className="font-mono">{g.forest}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Td>
          <Td className="text-[12px] text-text-2">
            {/* Nine forests granted whole is one fact, not nine rows of it.
                Where they do differ, the rows line up with the forests
                named beside them in the previous column. */}
            <div className="space-y-1">
              {(uniform(p.grants) ? p.grants.slice(0, 1) : p.grants).map((g) => (
                <div key={g.forest} className="flex min-h-[19px] items-center font-mono">
                  {g.allow?.length === 1 && g.allow[0] === ''
                    ? t('access.scope_all')
                    : g.allow.map((a) => a.replace(/\/$/, '')).join(', ')}
                  {g.deny?.length > 0 && (
                    <span className="text-danger"> − {g.deny.join(', ')}</span>
                  )}
                </div>
              ))}
            </div>
          </Td>
          <Td>
            {p.has_password ? <Badge tone="accent">{t('people.password_yes')}</Badge>
                            : <Badge>{t('people.password_no')}</Badge>}
          </Td>
          <Td className="tabular-nums text-text-2">{p.live_tokens}</Td>
          <Td className="whitespace-nowrap text-[12px] text-text-3">
            {p.last_seen ? p.last_seen.replace('T', ' ').slice(0, 16) : t('tokens.unused')}
          </Td>
          <Td>
            <div className="flex justify-end">
              <button className="btn btn-sm" onClick={() => onOpen(p.id)}
                      disabled={!p.manageable} title={!p.manageable
                        ? t('people.not_manageable') : undefined}>
                {t('people.manage')}
              </button>
            </div>
          </Td>
        </tr>
      ))}
    </Table>
  )
}

/** Which forests a person reaches, in the width of a badge.
 *
 *  One forest is named outright. Several collapse to a count — but a count
 *  nobody can expand is worse than the list it replaced, so the names come
 *  back on hover. A `title` rather than a floating panel on purpose: this
 *  lives inside the table's horizontal scroll container, which would clip a
 *  positioned tooltip on the first and last rows.
 */
function ForestsBadge({ grants }) {
  const { t } = useI18n()
  if (grants.length === 0) return null
  if (grants.length === 1) {
    return <Badge className="font-mono">{grants[0].forest}</Badge>
  }
  return (
    <Badge className="cursor-help" title={grants.map((g) => g.forest).join('\n')}>
      {t('people.forests_n', { n: grants.length })}
    </Badge>
  )
}

/** The credential-shaped view of the same truth: what exists, rather than
 *  who exists. Two views, one place to maintain them. */
function TokenTable({ people, onChanged }) {
  const { t } = useI18n()
  const tokens = people.flatMap((p) => (p.tokens || []).map((k) => ({ ...k, who: p.id })))
  if (tokens.length === 0) {
    return <Empty icon={Key} title={t('tokens.none')}>{t('tokens.none_hint')}</Empty>
  }
  return (
    <Table head={[t('tokens.label'), t('common.principal'), t('tokens.prefix'),
                  t('tokens.expires'), t('tokens.last_used'), t('audit.result'), '']}>
      {tokens.map((k) => (
        <tr key={k.id} className={k.status === 'active' ? '' : 'opacity-60'}>
          <Td className="font-medium text-text">{k.label || '—'}</Td>
          <Td className="text-text-2">{k.who}</Td>
          <Td className="font-mono text-[11.5px] text-text-3">{k.prefix ? `${k.prefix}…` : '—'}</Td>
          <Td className="whitespace-nowrap text-[12px] text-text-3">
            {k.expires_at ? k.expires_at.slice(0, 10) : t('tokens.never')}
          </Td>
          <Td className="whitespace-nowrap text-[12px] text-text-3">
            {k.last_used_at ? k.last_used_at.replace('T', ' ').slice(0, 16)
                            : t('tokens.unused')}
          </Td>
          <Td>
            {k.status === 'active' ? <Badge tone="accent">{t('tokens.active')}</Badge>
              : k.status === 'expired' ? <Badge tone="warn">{t('tokens.expired')}</Badge>
              : <Badge tone="danger">{t('tokens.revoked')}</Badge>}
          </Td>
          <Td>
            {k.status === 'active' && (
              <div className="flex justify-end">
                <button className="btn btn-sm btn-danger" title={t('tokens.revoke')}
                        onClick={() => api.savePerson({ principal: k.who,
                                                        revoke_keys: [k.id] })
                          .then(onChanged)}>
                  <Trash size={13} />
                </button>
              </div>
            )}
          </Td>
        </tr>
      ))}
    </Table>
  )
}

/** Everything about one person, in one place: who, what they may see, how
 *  they sign in, and their tokens. Creating and maintaining use the same
 *  form, because they are the same decision made at different times. */
function PersonDrawer({ person, forests, me, defaultForest, onClose, onSaved }) {
  const { t } = useI18n()
  const isNew = !person
  const held = useMemo(() => (person?.grants || []).map((g) => g.forest), [person])
  const existing = person?.grants?.[0]

  const [form, setForm] = useState(() => ({
    principal: person?.id || '',
    // Access is a set of forests, not one of them (J.2.3): an existing
    // person opens with everything they hold already ticked, so the box
    // reads as their access rather than as a fresh question.
    forests: person ? (person.grants || []).map((g) => g.forest)
      : [defaultForest, forests[0]].filter((f) => f && forests.includes(f)).slice(0, 1),
    role: roleOf(existing?.caps || ROLES.reader),
    caps: existing?.caps || ROLES.reader,
    scopeAll: !existing || (existing.allow?.length === 1 && existing.allow[0] === ''),
    allow: (existing?.allow || []).filter(Boolean).map((a) => a.replace(/\/$/, '')),
    setPassword: isNew,
    password: '',
    issueKey: isNew,
    keyLabel: '',
    keyDays: 90,
  }))
  const [state, setState] = useState({})

  // Branch names are forest-local, so the subtree picker only means
  // something for exactly one forest — and it must read *that* forest's
  // branches, walked with the operator's own grant on it.
  const single = form.forests.length === 1 ? form.forests[0] : null
  const mine = useMemo(
    () => (me?.grants || []).find((g) => g.forest === single) || null, [me, single])
  const tree = useForestTree(single, mine, api.call)
  const names = useMemo(
    () => (tree.data?.branches || []).map((b) => branchOf(b.id)).filter(Boolean),
    [tree.data])

  // Levels are per forest in the registry; this form applies one to all of
  // them, so a person who already differs between forests is told what
  // saving would flatten.
  const mixed = held.length > 1 && !uniform(person.grants)

  const chooseForests = (next) => setForm((f) => {
    const wasSingle = f.forests.length === 1 ? f.forests[0] : null
    const nowSingle = next.length === 1 ? next[0] : null
    // A branch list from another forest is not a scope, it is a guess.
    const moved = nowSingle !== wasSingle
    return { ...f, forests: next,
             scopeAll: nowSingle ? (moved ? true : f.scopeAll) : true,
             allow: moved ? [] : f.allow }
  })
  const chooseRole = (role) => setForm((f) => ({ ...f, role, caps: ROLES[role] || f.caps }))
  const toggleCap = (c) => setForm((f) => {
    const caps = f.caps.includes(c) ? f.caps.filter((x) => x !== c) : [...f.caps, c]
    return { ...f, caps, role: roleOf(caps) }
  })

  async function save(e) {
    e.preventDefault()
    setState({ busy: true })
    const body = { principal: form.principal.trim() }
    if (form.forests.length) {
      body.grant = {
        forests: form.forests, caps: form.caps,
        allow: form.scopeAll ? [] : form.allow.map((b) => `${b}/`),
      }
    }
    // Unticking a forest this person holds is the plain reading of the box,
    // so it revokes rather than being quietly ignored.
    const dropped = held.filter((f) => !form.forests.includes(f))
    if (dropped.length) body.revoke_access = dropped
    if (form.setPassword) body.password = form.password
    if (form.issueKey) {
      body.issue_key = { label: form.keyLabel || undefined,
                         expires_in_days: form.keyDays ? Number(form.keyDays) : null }
    }
    try {
      const res = await api.savePerson(body)
      if (res.refused?.length) setState({ busy: false, refused: res.refused, res })
      else onSaved(res)
    } catch (error) { setState({ busy: false, error }) }
  }

  const noForest = form.forests.length === 0
  const noBranch = Boolean(single) && !form.scopeAll && form.allow.length === 0
  const nothing = noBranch || (isNew && noForest)

  return (
    <Modal open wide onClose={onClose}
           title={isNew ? t('people.new_title') : person.id}
           subtitle={isNew ? t('people.new_sub') : t('people.edit_sub')}
           footer={<>
             <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
             <button className="btn btn-primary" form="person"
                     disabled={state.busy || !form.principal.trim() || nothing}>
               {state.busy ? t('common.working')
                 : isNew ? t('people.create') : t('common.save')}
             </button>
           </>}>
      <form id="person" onSubmit={save} className="space-y-6">
        {isNew && (
          <Field label={t('access.who')} value={form.principal} required autoFocus
                 placeholder={t('access.who_ph')} hint={t('people.who_hint')}
                 onChange={(e) => setForm({ ...form, principal: e.target.value })} />
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <CheckList
            label={t('access.forests')} hint={t('access.forests_hint')}
            options={forests.map((f) => ({ value: f }))}
            value={form.forests} onChange={chooseForests}
            allLabel={t('access.forests_all')}
            filterPlaceholder={t('access.forests_filter')}
            empty={t('access.forests_none')} />
          <div>
            <Select label={t('access.role')} value={form.role}
                    onChange={(e) => chooseRole(e.target.value)}>
              {Object.keys(ROLES).map((r) => (
                <option key={r} value={r}>{t(`role.${r}`)}</option>
              ))}
              <option value="custom" disabled>{t('role.custom')}</option>
            </Select>
            <p className="mt-1.5 text-[11.5px] text-text-3">{t(`role.${form.role}_desc`)}</p>
            {form.forests.length > 1 && (
              <p className="mt-2 text-[11.5px] text-text-3">
                {t('access.forests_same_level', { n: form.forests.length })}
              </p>
            )}
          </div>
        </div>

        {noForest && (
          <Note tone="warn">
            {isNew ? t('access.forests_pick_one') : t('access.forests_drop_all')}
          </Note>
        )}
        {mixed && <Note tone="warn">{t('access.forests_mixed')}</Note>}

        <details>
          <summary className="cursor-pointer text-[12px] text-text-3 hover:text-accent">
            {t('access.advanced')}
          </summary>
          <div className="mt-2 flex flex-wrap gap-1.5 rounded-lg border border-line
                          bg-surface-2 p-3">
            {ALL_CAPS.map((c) => (
              <button key={c} type="button" onClick={() => toggleCap(c)}
                      className={`badge ${form.caps.includes(c)
                        ? 'badge-accent' : 'hover:border-line-strong'}`}>
                {c}
              </button>
            ))}
          </div>
        </details>

        <div>
          <span className="label">{t('access.scope')}</span>
          {single ? (
            <>
              <div className="grid gap-2 sm:grid-cols-2">
                {[[true, 'access.scope_all'], [false, 'access.scope_pick']].map(([v, key]) => (
                  <button key={String(v)} type="button"
                          onClick={() => setForm({ ...form, scopeAll: v })}
                          className={`rounded-lg border p-3 text-left text-[13px] transition
                            ${form.scopeAll === v
                              ? 'border-accent bg-accent-soft text-accent'
                              : 'border-line bg-surface-2 text-text hover:border-line-strong'}`}>
                    {t(key)}
                  </button>
                ))}
              </div>
              {!form.scopeAll && (
                <div className="mt-3 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto
                                rounded-lg border border-line bg-surface-2 p-3">
                  {tree.busy ? <Spinner label={t('common.loading')} />
                    : names.length === 0 ? (
                      <p className="text-[12px] text-text-3">{t('access.scope_no_branches')}</p>
                    ) : names.map((b) => (
                      <button key={b} type="button"
                              onClick={() => setForm((f) => ({ ...f,
                                allow: f.allow.includes(b) ? f.allow.filter((x) => x !== b)
                                                           : [...f.allow, b] }))}
                              className={`badge font-mono ${form.allow.includes(b)
                                ? 'badge-accent' : 'hover:border-line-strong'}`}>
                        {b}
                      </button>
                    ))}
                </div>
              )}
              {noBranch && (
                <div className="mt-2"><Note tone="warn">{t('access.preview_none')}</Note></div>
              )}
            </>
          ) : (
            // Several forests (or none) selected: a branch prefix from one
            // forest is meaningless in another, so the grant covers each
            // forest whole and says so (J.5.5).
            <Note>{noForest ? t('access.scope_needs_forest') : t('access.scope_multi')}</Note>
          )}
        </div>

        <div className="space-y-3 rounded-lg border border-line p-3.5">
          <Toggle checked={form.setPassword}
                  onChange={(v) => setForm({ ...form, setPassword: v })}
                  label={person?.has_password ? t('people.change_password')
                                              : t('people.give_password')}
                  hint={t('people.password_hint')} />
          {form.setPassword && (
            <Field type="password" value={form.password} autoComplete="new-password"
                   placeholder={t('tokens.new_password')}
                   hint={t('people.password_clear_hint')}
                   onChange={(e) => setForm({ ...form, password: e.target.value })} />
          )}
        </div>

        <div className="space-y-3 rounded-lg border border-line p-3.5">
          <Toggle checked={form.issueKey}
                  onChange={(v) => setForm({ ...form, issueKey: v })}
                  label={t('people.give_token')} hint={t('people.token_hint')} />
          {form.issueKey && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('tokens.label')} value={form.keyLabel}
                     placeholder={t('tokens.label_ph')}
                     onChange={(e) => setForm({ ...form, keyLabel: e.target.value })} />
              <Select label={t('tokens.expires')} value={form.keyDays}
                      onChange={(e) => setForm({ ...form, keyDays: e.target.value })}>
                {LIFETIMES.map((d) => (
                  <option key={d} value={d}>{t('tokens.days', { n: d })}</option>
                ))}
                <option value="">{t('tokens.never')}</option>
              </Select>
            </div>
          )}
        </div>

        {!isNew && (
          <div className="flex flex-wrap gap-2 border-t border-line pt-4">
            <button type="button" className="btn btn-sm"
                    onClick={() => api.savePerson({ principal: person.id, password: '' })
                      .then(() => onSaved(null))}>
              {t('people.clear_password')}
            </button>
            <button type="button" className="btn btn-sm btn-danger"
                    onClick={() => api.savePerson({ principal: person.id, revoke_keys: true })
                      .then(() => onSaved(null))}>
              {t('people.revoke_all')}
            </button>
            <button type="button" className="btn btn-sm btn-danger" disabled={!held.length}
                    onClick={() => api.savePerson({ principal: person.id,
                                                    revoke_access: held })
                      .then(() => onSaved(null))}>
              {t('people.revoke_access')}
            </button>
          </div>
        )}

        <ErrorNote error={state.error} />
        {state.refused?.length > 0 && (
          <Note tone="warn">
            {t('people.partly_applied')}
            <ul className="mt-1 list-disc pl-4">
              {state.refused.map((r, i) => (
                <li key={i}>
                  {r.step}{r.forest ? ` (${r.forest})` : ''}: {r.message}
                </li>
              ))}
            </ul>
          </Note>
        )}
      </form>
    </Modal>
  )
}

function Levels() {
  const { t } = useI18n()
  return (
    <Card title={t('access.levels')} subtitle={t('access.levels_sub')} icon={Shield}>
      <Table head={[t('access.role'), t('overview.can'), t('overview.cannot')]}>
        {Object.entries(ROLES).map(([role, caps]) => (
          <tr key={role}>
            <Td>
              <span className="block text-[13px] font-medium text-text">{t(`role.${role}`)}</span>
              <span className="mt-0.5 block text-[11.5px] text-text-3">{t(`role.${role}_desc`)}</span>
            </Td>
            <Td className="text-[12.5px] text-text-2">
              {caps.map((c) => t(`cap.${c}`)).join(', ')}
            </Td>
            <Td className="text-[12.5px] text-text-3">
              {ALL_CAPS.filter((c) => !caps.includes(c)).map((c) => t(`cap.${c}`)).join(', ') || '—'}
            </Td>
          </tr>
        ))}
      </Table>
      <div className="mt-4"><Note>{t('access.levels_note')}</Note></div>
    </Card>
  )
}
