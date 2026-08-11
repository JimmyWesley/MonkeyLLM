// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Programmer mode's tokenizers — colour JSON and SQL previews with the same
 * categorical hues the node-type legend uses (`--syntax-*` in index.css),
 * so the console reads like an editor without a second, unrelated palette.
 *
 * Hand-rolled regex scanners, not a dependency: everything this app renders
 * (request/response payloads, `tend`/`query` statements) is small and
 * well-formed, and a generic highlighter would ship a grammar for languages
 * nobody here writes.
 */
import { useDevMode } from '../devmode.jsx'

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

const TOKENIZERS = { json: tokenizeJson, sql: tokenizeSql }

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
}

/** Recolours `text` per `lang` while programmer mode is on; renders it
 *  verbatim otherwise, so every call site is safe with the mode off. */
export function Highlighted({ text, lang }) {
  const { on } = useDevMode()
  const tokenize = on ? TOKENIZERS[lang] : null
  if (!tokenize) return text
  return tokenize(text).map((tok, i) => (
    tok.cls ? <span key={i} className={CLASS[tok.cls]}>{tok.text}</span> : tok.text
  ))
}
