// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The reading surface, checked (spec J.5.4 / J.14 / J.14.1).
 *
 * An operator opened a PDF an extension had ingested. Three things went
 * wrong and none of them was a bug in the engine:
 *
 *  - the passport panel showed a 60-token `summary` with no label, and it
 *    read as "the model summarised my document" rather than as the SCENT
 *    `locate` searches, with the document itself whole underneath it;
 *  - the body was copied out of the rich editor, which round-trips markdown
 *    through HTML — the hard line breaks came back joined into one
 *    paragraph, every `_` came back as `\_`, and a `replace_body` nobody had
 *    typed appeared in the pending patch;
 *  - the tree offered `_assets/bfad6417-chatgpt--chatg.pdf`, a name composed
 *    out of a hash, and no way at all to get the original file back.
 *
 * Studio has no test runner and this file is not one: it reads the source of
 * the two views and RUNS the one decision that can be run without a browser.
 * `tests/test_studio_reading.py` runs it; a non-zero exit is a failed
 * criterion, named on stdout.
 *
 * The boundary is F.137's. What a reader of the source can see is the
 * decision layer — which function decides the surface, which route the bytes
 * come from, which field a label is computed from. What it cannot see is a
 * rendered panel or a clipboard, and asserting those from the source would
 * only assert that a string is present.
 *
 * The round trip is the exception, and deliberately so: it is a pure
 * function of a body, it lives in `src/roundtrip.js` with no React in it,
 * and it is the rule that failed. So it is exercised against real bodies —
 * including the shape that started this — rather than described.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { getSchema } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { DOMParser as PMDOMParser, DOMSerializer } from 'prosemirror-model'
import domino from '@mixmark-io/domino'

import {
  HEADING_LEVELS, normalised, richLossy, toHtml, toMarkdown,
} from './src/roundtrip.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (p) => readFileSync(join(here, p), 'utf8')
const editor = read('src/views/editor.jsx')
const files = read('src/views/files.jsx')
const locale = (lang) => JSON.parse(read(`src/locales/files/${lang}.json`))
const editorLocale = (lang) => JSON.parse(read(`src/locales/editor/${lang}.json`))
const LANGS = ['en', 'pt', 'es']

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

/* One function's body, found by its declaration and closed by brace depth,
   so a check reads THAT function and not a coincidence elsewhere. The scan
   starts at the LAST character of the signature, which every signature below
   ends with: starting at the first `{` after the name would count the braces
   of a destructured parameter list and close the body at the arguments. */
const bodyOf = (src, signature) => {
  const start = src.indexOf(signature)
  if (start < 0) return ''
  let depth = 0
  let i = src.indexOf('{', start + signature.length - 1)
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}' && --depth === 0) break
  }
  return src.slice(start, i + 1)
}

/* -- D1: the rich editor refuses what it cannot reproduce ---------------- */

/** The shape that started this: a converted PDF. `## Page 1`, a term and its
 *  value on two lines, prose hard-wrapped at the column the extractor used,
 *  and identifiers carrying underscores. */
const EXTRACTION = `## Page 1

Contribuinte
: STUDIO WEB CONSULTORIA EM INFORMATICA LTDA
Pessoa Jurídica
: Simples

The extraction keeps the hard line breaks the PDF had, so a paragraph
arrives wrapped at column seventy-two exactly like this one does, and the
next line belongs to the same sentence.

Identifiers such as snake_case_name and max_tokens appear in the body.
`

const PROSE = `## A heading

An ordinary paragraph the rich editor holds without changing a byte.

> And a quotation under it.
`

ok('D1 the criterion runs the round trip rather than naming shapes',
   /normalised\(toMarkdown\(toHtml\(md\)\)\) !== normalised\(md\)/
     .test(read('src/roundtrip.js')))
ok('D1 a PDF extraction is refused by the rich editor', richLossy(EXTRACTION))
ok('D1 the refusal is the round trip and not a pattern',
   normalised(toMarkdown(toHtml(EXTRACTION))) !== normalised(EXTRACTION))
ok('D1 ordinary prose still opens in the rich editor', !richLossy(PROSE))
ok('D1 the normalisation forgives trailing space and blank runs',
   !richLossy('## H\n\nA line.   \n\n\n\nAnother line.\n'))
ok('D1 the shapes the round trip cannot see are still named',
   richLossy('See [the docs](https://example.test).')
   && richLossy('![cap](media:notes/x)')
   && richLossy('| a | b |\n| - | - |\n')
   && richLossy('<div>raw</div>'))
ok('D1 a wikilink is not a link (the turndown rule holds)',
   !richLossy('See [[people/jimmy-wesley]] for the owner.'))

/* v0.84: the trip has to be FAITHFUL, not merely mechanical. Measured over
   the two forests, 33 of 82 fixture bodies and 37 of 154 bench bodies were
   refused the rich editor for two reasons, and both were turndown writing
   valid markdown that nobody types: `-   one` for `- one`, and
   `snake\_case` for `snake_case`. With the rules in `roundtrip.js` those
   counts are 20 and 31, and the criterion itself is untouched — what a body
   has to do to open in the rich editor is exactly what it had to do before.
   The residue is a blank line the trip inserts before a tight list, which
   is almost entirely `_index` bodies, and a table. */
ok('D1 a list comes back with the padding a person writes',
   toMarkdown(toHtml('- one\n- two\n')) === '- one\n- two')
ok('D1 a nested list re-parses as a nested list',
   toMarkdown(toHtml('- one\n  - nested\n- two\n')) === '- one\n  - nested\n- two')
ok('D1 an ordered item indents its continuation to its own marker',
   toMarkdown(toHtml('1. first\n\n   more\n\n2. second\n'))
     === '1. first\n\n   more\n\n2. second')
ok('D1 an identifier is not escaped mid-word',
   !richLossy('A max_tokens and a snake_case name.\n'))
ok('D1 an underscore that could open emphasis still is escaped',
   toMarkdown(toHtml('A \\_literal\\_ underscore.\n')).includes('\\_'),
   'intraword is safe; at a word boundary it is not')
ok('D1 a wikilink inside a list item survives, not only inside a paragraph',
   !richLossy('## Direct bananas\n\n- [[a/b]] — a summary.\n'))

ok('D1 the decision is taken before the rich surface opens',
   /const lossy = useMemo\(\(\) => richLossy\(orig\), \[orig\]\)/.test(editor)
   && /const start = lossy \? 'source' : 'rich'/.test(editor)
   && /if \(editor && start === 'rich'\) editor\.commands\.setContent/.test(editor))
ok('D1 rich mode is locked, with the hint the console already had',
   /disabled=\{lossy\}/.test(editor)
   && /title=\{lossy \? t\('editor\.rich_locked'\) : undefined\}/.test(editor)
   && /\{lossy && <Note>\{t\('editor\.rich_locked'\)\}<\/Note>\}/.test(editor))
ok('D1 the lock hint exists in the three languages and names no single shape',
   LANGS.every((lang) => {
     const text = editorLocale(lang)['editor.rich_locked']
     return text && !/table|tabela|tabla/i.test(text)
   }))

/* -- D2: an untouched rich body stages nothing --------------------------- */

/* The editor's baseline is `toMarkdown(toHtml(orig))` and its reading is
   `toMarkdown(editor.getHTML())`. Those are two different pipelines, and
   the second one is the one that writes: tiptap parses the HTML into ITS
   schema, and a node the schema has no room for is silently dropped. Run
   here on the same schema the editor configures, because that is the only
   way to know the two agree — with the levels the view shipped before
   (`[2, 3]`) every body in the fixture forest came back with its own `#`
   title demoted to a paragraph, and the pending patch said so. */
const schema = getSchema([StarterKit.configure({ heading: { levels: HEADING_LEVELS } })])
const doc = domino.createDocument('<!doctype html><html><body></body></html>')
const throughEditor = (md) => {
  const holder = doc.createElement('div')
  holder.innerHTML = toHtml(md)
  const parsed = PMDOMParser.fromSchema(schema).parse(holder)
  const out = doc.createElement('div')
  out.appendChild(DOMSerializer.fromSchema(schema)
    .serializeFragment(parsed.content, { document: doc }))
  return toMarkdown(out.innerHTML)
}

const TITLED = `# Nota Fiscal 2026-04

The body of a node, as every generator in this repository writes one.

## Page 1

A paragraph.
`
ok('D2 the rich schema holds every heading level a body carries',
   HEADING_LEVELS.includes(1) && HEADING_LEVELS.includes(4))
ok('D2 a body the editor admits stages no patch when nobody types',
   [PROSE, TITLED].every((md) => !richLossy(md)
     && throughEditor(md) === toMarkdown(toHtml(md))),
   'baseline === what the editor hands back')
ok('D2 the title of a node survives the rich surface',
   throughEditor(TITLED).startsWith('# Nota Fiscal 2026-04'))
ok('D2 the section grain compares against the round trip too',
   /const baseline = toMarkdown\(toHtml\(original\.body\)\)/.test(editor)
   && /if \(edited && edited !== baseline\) \{\s*patch\.replace_section/.test(editor))

/* -- D3: the copy is the stored file ------------------------------------- */

const copy = bodyOf(files, 'function CopyExport({ forest, id }) {')
ok('D3 the reading surface offers a copy of the markdown',
   /<CopyExport forest=\{forest\} id=\{file\.id\} \/>/.test(files)
   && copy.length > 0)
ok('D3 the copy comes from the export route (J.14.1)',
   /api\.exportNode\(forest, id\)/.test(copy))
ok('D3 the copy is never the editor\'s serialisation',
   !/toMarkdown|getHTML|turndown|marked/.test(copy)
   && !/roundtrip/.test(files))
ok('D3 the copy is named in the three languages',
   LANGS.every((lang) => locale(lang)['files.copy_markdown']
     && locale(lang)['files.copy_markdown_hint']))

/* -- E1: the scent and the body are labelled ----------------------------- */

const passport = bodyOf(files, 'function Passport({ forest, d, meta, onOpen }) {')
ok('E1 the summary is labelled as the scent, with its budget',
   /t\('files\.scent', \{ n: scent, max: SUMMARY_TOKENS \}\)/.test(passport)
   && /const scent = countTokens\(d\.summary\)/.test(passport))
ok('E1 the scent says what reads it',
   /t\('files\.scent_hint'\)/.test(passport))
ok('E1 the body line counts the sections and the tokens `look` returned',
   /const sections = `\$\{\(d\.outline \|\| \[\]\)\.length\}/.test(passport)
   && /t\('files\.body_line', \{ sections, tokens: d\.stats\?\.body_tokens \?\? 0 \}\)/
     .test(passport))
ok('E1 a clipped outline is reported as a floor, never as a count',
   /const clipped = \(d\.truncated_fields \|\| \[\]\)\.includes\('outline'\)/.test(passport))
ok('E1 the body size is not printed twice',
   !/explore\.tokens/.test(files))
ok('E1 the panel still reads one unfiltered `look`',
   /useAsync\(\(\) => api\.call\(forest, 'look', \{ id: node \}\)/.test(files)
   && !/'look', \{ id: node, fields/.test(files))
const labelled = LANGS.every((lang) => {
  const d = locale(lang)
  return ['files.scent', 'files.scent_hint', 'files.body_label', 'files.body_line',
          'files.body_line_tokens'].every((k) => d[k])
    && d['files.scent'].includes('{n}') && d['files.scent'].includes('{max}')
    && d['files.body_line'].includes('{sections}')
})
ok('E1 every label exists in the three languages, placeholders intact', labelled)

/* -- A2: the original -------------------------------------------------- */

const original = bodyOf(files, 'function Original({ forest, d, meta }) {')
ok('A2 the original is read from the digest, never from a second call',
   /d\.payload_missing/.test(original)
   && /d\.payload_type/.test(original) && /d\.payload_bytes/.test(original))
ok('A2 the bytes come through the J.14 route with the viewer\'s credential',
   /await api\.payload\(forest, d\.id\)/.test(original)
   && /URL\.createObjectURL\(await p\.blob\(\)\)/.test(original)
   && /a\.download = name/.test(original))
ok('A2 a payload the forest does not have says so instead of offering it',
   /if \(d\.payload_missing\) \{[^]*?files\.original_missing/.test(original))
ok('A2 a node with no payload gets no line at all',
   /if \(d\.payload_type === undefined && d\.payload_bytes === undefined\) return null/
     .test(original))
ok('A2 a remote payload is named and not offered (J.14 serves local bytes)',
   /const local = typeof d\.payload_bytes === 'number'/.test(original)
   && /\{local && \(/.test(original))
ok('A2 the panel mounts it', /<Original forest=\{forest\} d=\{d\} meta=\{meta\} \/>/.test(files))
ok('A2 named in the three languages',
   LANGS.every((lang) => ['files.original', 'files.original_download',
                          'files.original_missing', 'files.original_remote']
     .every((k) => locale(lang)[k])))

/* -- A3: the archive is not a file a person browses ---------------------- */

ok('A3 `_assets` is matched as a directory at any depth, never as a prefix',
   /const ASSETS_DIR = \/\(\?:\^\|\\\/\)_assets\\\/\//.test(files))
ok('A3 the listing drops it, and the drop is in the listing alone',
   /if \(inAssets\(path\)\) continue/.test(bodyOf(files, 'export function filesOf(nodes) {')))
ok('A3 the catalog is untouched — no filter on the map projection',
   !/nodes\.filter\(/.test(files))

if (failed) {
  console.log(`\n${failed} criterion(s) failed`)
  process.exit(1)
}
console.log('\nall reading criteria hold')
