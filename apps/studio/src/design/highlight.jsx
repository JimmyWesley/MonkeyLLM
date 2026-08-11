// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Syntax colour, everywhere the console shows source.
 *
 * This is not a decoration and it is not a mode: MonkeyLLM is an instrument,
 * and every literal surface it prints — a request body, a `tend` statement,
 * a passport, a stored markdown body, a curl line in the manual, a fenced
 * block inside an answer — is read as *structure* by the person reading it.
 * Colour is how structure becomes visible without a second reading. So it is
 * always on, for every language this console can name, and there is no switch
 * to turn it off: a preference that only ever moved in one direction was a
 * preference in name only.
 *
 * The hues are the node-type legend's (`--syntax-*` in index.css), so the
 * console never carries a second, unrelated palette — a key is the blue that
 * documents are, a string the orange that events are.
 *
 * Hand-rolled regex scanners, not a dependency. Everything rendered here is
 * small and well-formed, and a general highlighter would ship grammars for a
 * hundred languages to colour the seven this console actually prints.
 */
import { useMemo } from 'react'

/** Splits `text` into `{text, cls}` runs by trying each named group of
 *  `pattern` in turn; the gaps between matches (whitespace, punctuation the
 *  grammar doesn't care about) come back as `cls: null`. */
function scan(text, pattern) {
  const tokens = []
  let last = 0
  for (const m of text.matchAll(pattern)) {
    if (m.index > last) tokens.push({ text: text.slice(last, m.index), cls: null })
    const cls = Object.keys(m.groups).find((k) => m.groups[k] !== undefined)
    tokens.push({ text: m[0], cls })
    last = m.index + m[0].length
  }
  if (last < text.length) tokens.push({ text: text.slice(last), cls: null })
  return tokens
}

/* -- JSON ---------------------------------------------------------------- */

const JSON_TOKEN = new RegExp(
  '(?<key>"(?:\\\\.|[^"\\\\])*"(?=\\s*:))' +
  '|(?<string>"(?:\\\\.|[^"\\\\])*")' +
  '|(?<number>-?\\d+\\.?\\d*(?:[eE][+-]?\\d+)?)' +
  '|(?<keyword>\\btrue\\b|\\bfalse\\b|\\bnull\\b)' +
  '|(?<punct>[{}[\\],:])',
  'g',
)

export function tokenizeJson(text) {
  return scan(text, JSON_TOKEN)
}

/* -- SQL ----------------------------------------------------------------- */

const SQL_KEYWORDS = new Set([
  'select', 'from', 'where', 'insert', 'into', 'values', 'update', 'set',
  'delete', 'join', 'left', 'right', 'inner', 'outer', 'on', 'and', 'or',
  'not', 'in', 'is', 'null', 'order', 'by', 'group', 'having', 'limit',
  'offset', 'as', 'distinct', 'create', 'table', 'desc', 'asc', 'like',
  'between', 'union', 'all', 'count', 'sum', 'avg', 'min', 'max', 'case',
  'when', 'then', 'else', 'end',
])

const SQL_TOKEN = new RegExp(
  '(?<comment>--[^\\n]*)' +
  "|(?<string>'(?:''|[^'])*')" +
  '|(?<number>\\b\\d+\\.?\\d*\\b)' +
  '|(?<word>[A-Za-z_][A-Za-z0-9_]*)' +
  '|(?<punct>[(),.;*=<>!+/-])',
  'g',
)

export function tokenizeSql(text) {
  return scan(text, SQL_TOKEN).map((tok) => (
    tok.cls === 'word'
      ? { ...tok, cls: SQL_KEYWORDS.has(tok.text.toLowerCase()) ? 'keyword' : null }
      : tok
  ))
}

/* -- shell --------------------------------------------------------------- */

const SHELL_TOKEN = new RegExp(
  '(?<comment>#[^\\n]*)' +
  '|(?<link>[a-z][a-z0-9+.-]*://[^\\s\'"`]+)' +
  '|(?<string>\'[^\']*\'|"(?:\\\\.|[^"\\\\])*")' +
  '|(?<var>\\$\\{[^}\\n]*\\}|\\$[A-Za-z_][A-Za-z0-9_]*)' +
  '|(?<key>--?[A-Za-z][A-Za-z0-9-]*)' +
  '|(?<number>\\b\\d+\\b)' +
  '|(?<word>[A-Za-z_][A-Za-z0-9_./-]*)' +
  '|(?<punct>[|&;<>()={}])',
  'g',
)

/** `$KEY` inside double quotes is still a variable — an `Authorization`
 *  header that prints the placeholder in the same colour as the literal
 *  around it hides the one part of that line the reader has to substitute. */
const SHELL_INTERP = new RegExp(
  '(?<var>\\$\\{[^}\\n]*\\}|\\$[A-Za-z_][A-Za-z0-9_]*)', 'g')

const interpolate = (text) => scan(text, SHELL_INTERP)
  .map((tok) => (tok.cls ? tok : { ...tok, cls: 'string' }))

export function tokenizeShell(text) {
  const out = []
  // The first bare word of a command is the command; the rest are arguments.
  // Tracked as a walk rather than matched with a lookbehind, because what
  // opens a command (a newline, a pipe, `&&`) is context, not a character.
  let atStart = true
  for (const tok of scan(text, SHELL_TOKEN)) {
    if (tok.cls === 'word') {
      out.push({ ...tok, cls: atStart ? 'keyword' : null })
      atStart = false
      continue
    }
    if (tok.cls === 'string' && tok.text[0] === '"') {
      out.push(...interpolate(tok.text))
      continue
    }
    // A trailing backslash means the next line is still this command's
    // arguments, so the flag that opens it is not a command name.
    if (tok.cls === null && tok.text.includes('\n')) atStart = !/\\[ \t]*\n/.test(tok.text)
    else if (tok.cls === 'punct' && /[|&;]/.test(tok.text)) atStart = true
    out.push(tok)
  }
  return out
}

/* -- YAML ---------------------------------------------------------------- */

/* Line-based rather than one scanner: in YAML "is this a key" is a question
 * about position in the line, and a pattern loose enough to find keys
 * anywhere would colour the colon inside a summary sentence. */
const YAML_LINE = /^([ \t]*)((?:-[ \t]+)?)([A-Za-z_][\w.-]*)(:)(.*)$/
const YAML_SCALAR = new RegExp(
  '(?<string>"(?:\\\\.|[^"\\\\])*"|\'(?:\'\'|[^\'])*\')' +
  '|(?<keyword>\\b(?:true|false|null|yes|no)\\b)' +
  '|(?<number>-?\\b\\d[\\d.:-]*\\b)' +
  '|(?<punct>[[\\]{},])',
  'g',
)

export function tokenizeYaml(text) {
  const out = []
  String(text).split('\n').forEach((line, i) => {
    if (i) out.push({ text: '\n', cls: null })
    if (line.trim().startsWith('#')) { out.push({ text: line, cls: 'comment' }); return }
    const m = YAML_LINE.exec(line)
    if (!m) { out.push(...scan(line, YAML_SCALAR)); return }
    const [, indent, dash, key, colon, value] = m
    if (indent) out.push({ text: indent, cls: null })
    if (dash) out.push({ text: dash, cls: 'punct' })
    out.push({ text: key, cls: 'key' }, { text: colon, cls: 'punct' })
    out.push(...scan(value, YAML_SCALAR))
  })
  return out
}

/* -- markdown ------------------------------------------------------------ */

/* What a forest stores, shown as source. Headings and list markers carry the
 * shape of the document, and `[[wikilinks]]` are the trails — the three
 * things a reader looks for when they open the stored form instead of the
 * rendered one. */
const MD_TOKEN = new RegExp(
  '(?<heading>^#{1,6}[ \\t].*$)' +
  '|(?<comment>^[ \\t]*>.*$|^(?:---|\\*\\*\\*|___)[ \\t]*$)' +
  '|(?<punct>^[ \\t]*(?:[-*+]|\\d+\\.)(?=[ \\t]))' +
  '|(?<keyword>^[ \\t]*```.*$|\\*\\*[^*\\n]+\\*\\*|__[^_\\n]+__)' +
  '|(?<string>`[^`\\n]+`)' +
  // A bare URL ends before the sentence's punctuation does: `see https://x.`
  // is a link and a full stop, not a link with a full stop in it.
  '|(?<link>\\[\\[[^\\]\\n]+\\]\\]|!?\\[[^\\]\\n]*\\]\\([^)\\n]*\\)' +
  '|[a-z][a-z0-9+.-]*://[^\\s)\\]]*[^\\s)\\].,;:!?])',
  'gm',
)

export function tokenizeMarkdown(text) {
  return scan(text, MD_TOKEN)
}

/* -- .env ---------------------------------------------------------------- */

const ENV_TOKEN = new RegExp(
  '(?<comment>^[ \\t]*#[^\\n]*$)' +
  '|(?<key>^[ \\t]*[A-Za-z_][A-Za-z0-9_]*(?==))' +
  '|(?<link>[a-z][a-z0-9+.-]*://[^\\s]+)' +
  '|(?<keyword>\\b(?:true|false)\\b)' +
  '|(?<number>\\b\\d+\\b)' +
  '|(?<punct>=)',
  'gm',
)

export function tokenizeEnv(text) {
  return scan(text, ENV_TOKEN)
}

/* -- everything else ----------------------------------------------------- */

/* The fallback for a fence that names a language this console has no scanner
 * for. A model asked about a forest answers with Python as readily as with
 * SQL, and the shape shared by every curly-brace-and-quotes language —
 * comments, strings, numbers, reserved words — is most of what colour is
 * doing in a snippet anyway. */
const CODE_KEYWORDS = new Set([
  'and', 'as', 'assert', 'async', 'await', 'break', 'case', 'catch', 'class',
  'const', 'continue', 'def', 'default', 'del', 'elif', 'else', 'except',
  'export', 'extends', 'finally', 'for', 'from', 'function', 'global', 'if',
  'import', 'in', 'is', 'lambda', 'let', 'new', 'none', 'not', 'or', 'pass',
  'raise', 'return', 'self', 'switch', 'this', 'throw', 'try', 'typeof',
  'var', 'while', 'with', 'yield', 'true', 'false', 'null', 'undefined',
])

const CODE_TOKEN = new RegExp(
  '(?<comment>//[^\\n]*|#[^\\n]*|/\\*[\\s\\S]*?\\*/)' +
  '|(?<string>"(?:\\\\.|[^"\\\\\\n])*"|\'(?:\\\\.|[^\'\\\\\\n])*\'' +
  '|`(?:\\\\.|[^`\\\\])*`)' +
  '|(?<number>\\b\\d+\\.?\\d*\\b)' +
  '|(?<word>[A-Za-z_$][A-Za-z0-9_$]*)' +
  '|(?<punct>[{}()[\\].,;:=+*/<>!&|?-])',
  'g',
)

export function tokenizeCode(text) {
  return scan(text, CODE_TOKEN).map((tok) => (
    tok.cls === 'word'
      ? { ...tok, cls: CODE_KEYWORDS.has(tok.text.toLowerCase()) ? 'keyword' : null }
      : tok
  ))
}

/* -- picking a scanner --------------------------------------------------- */

const TOKENIZERS = {
  json: tokenizeJson,
  sql: tokenizeSql,
  bash: tokenizeShell,
  yaml: tokenizeYaml,
  markdown: tokenizeMarkdown,
  env: tokenizeEnv,
}

const ALIAS = {
  sh: 'bash', shell: 'bash', console: 'bash', curl: 'bash', zsh: 'bash',
  yml: 'yaml', md: 'markdown', dotenv: 'env', ini: 'env', '.env': 'env',
  sqlite: 'sql', jsonc: 'json', json5: 'json',
}

/* Guessing is the last resort, not the plan: every call site that knows what
 * it is printing says so. This exists for the one that cannot — a fenced
 * block in a model's answer with no language on the fence — and it stays
 * conservative, because miscolouring prose is worse than leaving it plain. */
const SNIFF = [
  [/^\s*[[{]/, 'json'],
  [/^[ \t]*[A-Z][A-Z0-9_]*=/m, 'env'],
  [/^\s*(?:select|insert|update|delete|create|with|pragma)\b/i, 'sql'],
  [/^[ \t]*(?:curl|docker|pip|python|npm|npx|claude|vine|station|git|cp|cd|export|sudo|ls|echo)\b/m,
   'bash'],
  [/^#{1,6}[ \t]|^[ \t]*[-*][ \t]|\[\[[^\]\n]+\]\]/m, 'markdown'],
  [/^[ \t]*[A-Za-z_][\w.-]*:[ \t]/m, 'yaml'],
]

const detect = (text) => SNIFF.find(([re]) => re.test(text))?.[1] || null

/** The tokens for `text`, or `null` when nothing here can say anything
 *  useful about it (an unnamed language that sniffs as prose, an API key). */
export function tokensOf(text, lang) {
  const body = String(text ?? '')
  if (!body) return null
  const named = String(lang ?? '').trim().toLowerCase()
  const tokenize = named
    ? (TOKENIZERS[ALIAS[named] || named] || tokenizeCode)
    : TOKENIZERS[detect(body)]
  return tokenize ? tokenize(body) : null
}

// Spelled out, not built as `syn-${cls}`: Tailwind's content scan matches
// literal class-name substrings in the source, and a template-interpolated
// one is invisible to it — the rule it would select silently never ships.
const CLASS = {
  key: 'syn-key',
  string: 'syn-string',
  number: 'syn-number',
  keyword: 'syn-keyword',
  punct: 'syn-punct',
  comment: 'syn-comment',
  var: 'syn-var',
  link: 'syn-link',
  heading: 'syn-heading',
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

/** The same colouring as `Highlighted`, as an HTML string — for the one
 *  caller that builds markup instead of elements (design/markdown.jsx, whose
 *  output goes through the sanitiser before it is inserted). Escaped here
 *  too: this function's output is markup, so its input must stop being it. */
export function highlightHtml(text, lang) {
  const tokens = tokensOf(text, lang)
  if (!tokens) return escapeHtml(text)
  return tokens.map((tok) => (tok.cls
    ? `<span class="${CLASS[tok.cls]}">${escapeHtml(tok.text)}</span>`
    : escapeHtml(tok.text))).join('')
}

/** Recolours `text` per `lang`; omit `lang` and the content is sniffed.
 *  Either way this renders `text` verbatim when nothing applies, so every
 *  call site is safe with any string. */
export function Highlighted({ text, lang }) {
  const tokens = useMemo(() => tokensOf(text, lang), [text, lang])
  if (!tokens) return text
  return tokens.map((tok, i) => (
    tok.cls ? <span key={i} className={CLASS[tok.cls]}>{tok.text}</span> : tok.text
  ))
}
