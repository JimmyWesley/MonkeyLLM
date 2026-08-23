// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* A ZIP writer — stored entries, no compression — for files the console
 * already holds in memory.
 *
 * The Skills console hands out a folder (J.5.12) and a person without a
 * shell should be able to receive it as a folder rather than as a paste.
 * That folder is a few kilobytes of markdown: there is nothing worth
 * compressing and no reason to carry a library to do it. Method 0 is what
 * every unzipper has understood since the format existed, and the whole of
 * it here is three records — local header, central directory, end record.
 *
 * Names carry their path (`monkeyllm-memory/references/saving.md`), which
 * is how a zip expresses a directory; no directory entries are written,
 * because every extractor creates the parents and some of them list an
 * empty entry as a stray file.
 */

/** The CRC-32 table, built once. */
const TABLE = (() => {
  const t = new Uint32Array(256)
  for (let i = 0; i < 256; i++) {
    let c = i
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    t[i] = c >>> 0
  }
  return t
})()

const crc32 = (bytes) => {
  let c = 0xffffffff
  for (let i = 0; i < bytes.length; i++) c = TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

/** MS-DOS date and time: two 16-bit words, two-second resolution, and an
 *  epoch of 1980 — older than the one everything else in this file uses. */
const dosStamp = (d) => ({
  time: ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xffff,
  date: (((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xffff,
})

/** Bit 11 of the general-purpose flags: the name below is UTF-8, not the
 *  format's ancient default code page. Every name we write is ASCII, but
 *  saying so costs a bit and stops an extractor from guessing. */
const UTF8 = 0x0800

function record(size, fill) {
  const buf = new Uint8Array(size)
  fill(new DataView(buf.buffer))
  return buf
}

/**
 * Build a ZIP from `[{path, text}]`.
 *
 * @returns {Blob} ready for a download link.
 */
export function zip(files, { at = new Date() } = {}) {
  const enc = new TextEncoder()
  const { time, date } = dosStamp(at)
  const body = []      // local headers + data, in order
  const central = []   // the directory, written after them
  let offset = 0

  for (const f of files) {
    const name = enc.encode(f.path)
    const data = enc.encode(f.text)
    const sum = crc32(data)

    const local = record(30 + name.length, (v) => {
      v.setUint32(0, 0x04034b50, true)   // local file header
      v.setUint16(4, 20, true)           // version needed
      v.setUint16(6, UTF8, true)
      v.setUint16(8, 0, true)            // method: stored
      v.setUint16(10, time, true)
      v.setUint16(12, date, true)
      v.setUint32(14, sum, true)
      v.setUint32(18, data.length, true) // compressed == uncompressed
      v.setUint32(22, data.length, true)
      v.setUint16(26, name.length, true)
      v.setUint16(28, 0, true)           // no extra field
    })
    local.set(name, 30)

    central.push({ name, sum, size: data.length, offset })
    body.push(local, data)
    offset += local.length + data.length
  }

  const dir = []
  let dirSize = 0
  for (const e of central) {
    const h = record(46 + e.name.length, (v) => {
      v.setUint32(0, 0x02014b50, true)   // central directory header
      v.setUint16(4, 20, true)           // version made by
      v.setUint16(6, 20, true)           // version needed
      v.setUint16(8, UTF8, true)
      v.setUint16(10, 0, true)           // method: stored
      v.setUint16(12, time, true)
      v.setUint16(14, date, true)
      v.setUint32(16, e.sum, true)
      v.setUint32(20, e.size, true)
      v.setUint32(24, e.size, true)
      v.setUint16(28, e.name.length, true)
      v.setUint16(30, 0, true)           // extra
      v.setUint16(32, 0, true)           // comment
      v.setUint16(34, 0, true)           // disk number
      v.setUint16(36, 0, true)           // internal attributes
      v.setUint32(38, 0, true)           // external attributes
      v.setUint32(42, e.offset, true)
    })
    h.set(e.name, 46)
    dir.push(h)
    dirSize += h.length
  }

  const end = record(22, (v) => {
    v.setUint32(0, 0x06054b50, true)     // end of central directory
    v.setUint16(4, 0, true)              // this disk
    v.setUint16(6, 0, true)              // disk with the directory
    v.setUint16(8, central.length, true)
    v.setUint16(10, central.length, true)
    v.setUint32(12, dirSize, true)
    v.setUint32(16, offset, true)        // where the directory starts
    v.setUint16(20, 0, true)             // no archive comment
  })

  return new Blob([...body, ...dir, end], { type: 'application/zip' })
}
