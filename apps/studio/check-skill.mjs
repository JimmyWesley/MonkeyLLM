// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* J.5.12 acceptance (F.111 - F.115): the generated skill, checked.
 *
 * Studio has no test runner and this file is not one — it is the console's
 * one artifact that a machine can check, so it is checked where it is made.
 * `tests/test_skill_console.py` runs it; a non-zero exit is a failed
 * criterion, named on stdout. */
import { BLOCKS, buildSkill, defaultBlocks, inlineSkill, installScript, tokens }
  from './src/skill.js'
import { zip } from './src/zip.js'

let failed = 0

const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}
const ctx = (caps, forests) => ({ origin: 'https://x.test', station: '0.60.0', caps, forests })

// F.111 — a {read, ingest} key gets no write instructions, and a smaller core
const c1 = ctx(['read', 'ingest'], [{ id: 'f', caps: ['read', 'ingest'] }])
const sel1 = defaultBlocks(c1.caps)
const files1 = buildSkill(c1, sel1)
const core1 = files1[0].text
const writes = ['plant(', 'graft(', 'prune(', 'transplant(', 'tend(']
ok('F.111 core teaches no write', !writes.some((w) => core1.includes(w)),
   `core ${tokens(core1)} tok vs 3921 before`)
ok('F.111 saving shipped, writing not',
   sel1.includes('saving') && !sel1.includes('writing'), sel1.join(','))
ok('F.111 core smaller than the file it replaces', tokens(core1) < 3921)
ok('F.111 every reference is named in the core with its trigger',
   files1.slice(1).every((f) => core1.includes(f.path))
   && BLOCKS.filter((b) => sel1.includes(b.id)).every((b) => core1.includes(b.when)))

// F.112 — every example names the forest
const TOOLS = ['locate', 'look', 'pick', 'move', 'scan', 'sniff', 'harvest', 'answer',
               'calendar', 'coverage', 'view', 'history', 'query', 'plant', 'graft',
               'prune', 'transplant', 'tend', 'ingest']
const all = buildSkill(ctx(['read', 'ingest', 'write', 'query', 'tend'],
                           [{ id: 'f', caps: ['read'] }]), BLOCKS.map((b) => b.id))
const bare = all.flatMap((f) => f.text.split('\n')
  .filter((l) => TOOLS.some((t) => new RegExp(`\\b${t}\\((?!forest)`).test(l)))
  .map((l) => `${f.path}: ${l.trim().slice(0, 60)}`))
ok('F.112 every call example names the forest', bare.length === 0, bare.join(' | '))

// F.113 — routing table only for several forests, forests() taught by both
const two = ctx(['read'], [{ id: 'a', caps: ['read'], roots: [{ title: 'P', nodes: 4 }] },
                           { id: 'b', caps: ['read'], roots: [{ title: 'Q', nodes: 9 }] }])
const twoCore = buildSkill(two, [])[0].text
ok('F.113 two forests carry a routing table',
   twoCore.includes('## Which forest') && twoCore.includes('| `a` |') && twoCore.includes('| `b` |'))
ok('F.113 one forest carries none, teaches coverage()',
   !core1.includes('## Which forest') && core1.includes('coverage(forest)'))
ok('F.113 both teach forests() first',
   [core1, twoCore].every((t) => t.includes('## Call forests() first')))

// F.114 — default equals the key's caps; an over-selected block states its need
ok('F.114 default selection equals the key', defaultBlocks(['read']).join(',') === 'time,sharing'
   && defaultBlocks(['read', 'write', 'query']).join(',') === 'writing,time,datasets,sharing')
const over = buildSkill(c1, ['writing'])
ok('F.114 a block beyond the key names the capability',
   over[1].text.includes('Requires the `write` capability'))

// F.115 — the two assemblies teach the same instructions
const norm = (t) => t.replace(/^#+ /gm, '').replace(/\s+/g, ' ').trim()
const folder = buildSkill(c1, sel1)
const single = inlineSkill(c1, sel1)
const missing = folder.slice(1).filter((f) => {
  const body = norm(f.text).split(' ').slice(4).join(' ')
  return !norm(single[0].text).includes(body.slice(0, 400))
})
ok('F.115 one file carries every block of the folder', missing.length === 0,
   missing.map((f) => f.path).join(','))
ok('F.115 single file is one file', single.length === 1)

// the install script writes exactly the files, with quoted heredocs
const script = installScript(folder)
ok('install script writes every file',
   folder.every((f) => script.includes(`~/.claude/skills/monkeyllm-memory/${f.path} <<'MONKEYLLM_SKILL'`)))
ok('install script never lets the shell expand a skill',
   !script.includes('<<MONKEYLLM_SKILL') && !folder.some((f) => f.text.includes('MONKEYLLM_SKILL')))

// F.116 — the generated half. That the console reads and writes the address
// needs a DOM; what is checkable here is that the file names the link and
// leaves installing to a person.
const back = { ...ctx(['read'], [{ id: 'f', caps: ['read'] }]),
               reinstall: 'https://x.test/f/f/skills?forests=f&blocks=time' }
const backCore = buildSkill(back, ['time'])[0].text
ok('F.116 the core names the address that rebuilds it', backCore.includes(back.reinstall))
ok('F.116 installing is stated as the operator\'s act',
   backCore.includes('cannot install it yourself'))
ok('F.116 no generated file offers a skill tool or route',
   !buildSkill(back, BLOCKS.map((b) => b.id)).some((f) => /skill\(|\/v1\/skill/.test(f.text)))

// The archive: a corrupt zip is exactly the kind of thing that ships quietly,
// so the central directory is read back and compared against the source.
const zipped = buildSkill(ctx(['read', 'ingest', 'write', 'query', 'tend'],
                              [{ id: 'f', caps: ['read'] }]), BLOCKS.map((b) => b.id))
  .map((f) => ({ ...f, path: `monkeyllm-memory/${f.path}` }))
const bytes = new Uint8Array(await zip(zipped).arrayBuffer())
const view = new DataView(bytes.buffer)
const dec = new TextDecoder()

// End-of-central-directory is the last 22 bytes when there is no comment.
const eocd = bytes.length - 22
const count = view.getUint16(eocd + 8, true)
let at = view.getUint32(eocd + 16, true)
const seen = []
for (let i = 0; i < count; i++) {
  const nameLen = view.getUint16(at + 28, true)
  seen.push({ name: dec.decode(bytes.subarray(at + 46, at + 46 + nameLen)),
              size: view.getUint32(at + 24, true) })
  at += 46 + nameLen + view.getUint16(at + 30, true) + view.getUint16(at + 32, true)
}
ok('zip: end record signed, one entry per file',
   view.getUint32(eocd, true) === 0x06054b50 && count === zipped.length)
ok('zip: every path arrives under the folder, arranged',
   zipped.every((f) => seen.some((e) => e.name === f.path))
   && seen.every((e) => e.name.startsWith('monkeyllm-memory/')))
ok('zip: declared sizes match the text they came from',
   zipped.every((f) => {
     const e = seen.find((x) => x.name === f.path)
     return e && e.size === new TextEncoder().encode(f.text).length
   }))

process.exit(failed ? 1 : 0)
