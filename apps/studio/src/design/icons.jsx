/* Inline icons (spec J.5.1: navigation carries an icon per console).
 *
 * Hand-drawn on a 24-grid rather than pulled from a package: the set is
 * small, an icon font would be a second network asset the strict one-image
 * deployment does not need, and every glyph inherits `currentColor` so it is
 * correct in both themes for free.
 */

const S = ({ children, size = 18, className = '', ...rest }) => (
  <svg
    width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"
    strokeLinejoin="round" aria-hidden="true"
    className={`shrink-0 ${className}`} {...rest}
  >
    {children}
  </svg>
)

export const Overview = (p) => (
  <S {...p}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></S>
)
export const Ask = (p) => (
  <S {...p}><path d="M12 3l1.9 4.5L18.5 9.4 14 11.3 12 16l-1.9-4.7L5.5 9.4 10 7.5z" /><path d="M18 15.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z" /></S>
)
export const Explore = (p) => (
  <S {...p}><rect x="8.5" y="3" width="7" height="5" rx="1.5" /><rect x="2.5" y="16" width="7" height="5" rx="1.5" /><rect x="14.5" y="16" width="7" height="5" rx="1.5" /><path d="M12 8v3.5M6 16v-2a1.5 1.5 0 011.5-1.5h9A1.5 1.5 0 0118 14v2" /></S>
)
export const Playground = (p) => (
  <S {...p}><rect x="2.5" y="4" width="19" height="16" rx="2.5" /><path d="M7 9.5l2.5 2.5L7 14.5M12.5 15H17" /></S>
)
export const Data = (p) => (
  <S {...p}><ellipse cx="12" cy="5.5" rx="7.5" ry="2.8" /><path d="M4.5 5.5v6c0 1.6 3.4 2.9 7.5 2.9s7.5-1.3 7.5-2.9v-6" /><path d="M4.5 11.5v6c0 1.6 3.4 2.9 7.5 2.9s7.5-1.3 7.5-2.9v-6" /></S>
)
export const Ingest = (p) => (
  <S {...p}><path d="M12 15V3m0 0L8 7m4-4l4 4" /><path d="M3 14v3.5A3.5 3.5 0 006.5 21h11a3.5 3.5 0 003.5-3.5V14" /></S>
)
export const Models = (p) => (
  <S {...p}><rect x="7" y="7" width="10" height="10" rx="2" /><path d="M10 3v3M14 3v3M10 18v3M14 18v3M3 10h3M3 14h3M18 10h3M18 14h3" /></S>
)
export const Access = (p) => (
  <S {...p}><path d="M12 3l7.5 3v5.4c0 4.3-3 8.2-7.5 9.6-4.5-1.4-7.5-5.3-7.5-9.6V6z" /><path d="M9 12.2l2.1 2.1L15.4 10" /></S>
)
export const Audit = (p) => (
  <S {...p}><path d="M8 4.5H6.5A2.5 2.5 0 004 7v12a2.5 2.5 0 002.5 2.5h11A2.5 2.5 0 0020 19V7a2.5 2.5 0 00-2.5-2.5H16" /><rect x="8" y="2.5" width="8" height="4" rx="1.4" /><path d="M8.5 11.5h7M8.5 15.5h4.5" /></S>
)
export const Forest = (p) => (
  <S {...p}><path d="M12 2.5L6.5 11h3L5 17.5h14L14.5 11h3z" /><path d="M12 17.5v4" /></S>
)

export const Plus = (p) => <S {...p}><path d="M12 5v14M5 12h14" /></S>
export const Search = (p) => <S {...p}><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></S>
export const ChevronDown = (p) => <S {...p}><path d="M6 9.5l6 6 6-6" /></S>
export const ChevronRight = (p) => <S {...p}><path d="M9.5 6l6 6-6 6" /></S>
export const ChevronLeft = (p) => <S {...p}><path d="M14.5 6l-6 6 6 6" /></S>
export const Save = (p) => (
  <S {...p}><path d="M5 4.5h11l3.5 3.5v11.5a1 1 0 01-1 1H5a1 1 0 01-1-1v-14a1 1 0 011-1z" />
    <path d="M8 4.5v5h7v-5M8 19.5v-5h8v5" /></S>
)
export const Undo = (p) => (
  <S {...p}><path d="M4 9h11a4.5 4.5 0 010 9h-6" /><path d="M8 5L4 9l4 4" /></S>
)
export const Grid = (p) => (
  <S {...p}><rect x="3.5" y="4.5" width="17" height="15" rx="2" />
    <path d="M3.5 9.5h17M9.5 9.5v10" /></S>
)
export const Columns = (p) => (
  <S {...p}><rect x="3.5" y="4.5" width="17" height="15" rx="2" />
    <path d="M9.5 4.5v15M15 4.5v15" /></S>
)
export const Sun = (p) => (
  <S {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2.5M12 19.5V22M4.2 4.2l1.8 1.8M18 18l1.8 1.8M2 12h2.5M19.5 12H22M4.2 19.8L6 18M18 6l1.8-1.8" /></S>
)
export const Moon = (p) => <S {...p}><path d="M20 13.5A8.5 8.5 0 0110.5 4a8.5 8.5 0 109.5 9.5z" /></S>
export const Monitor = (p) => (
  <S {...p}><rect x="2.5" y="4" width="19" height="12.5" rx="2" /><path d="M8.5 20.5h7M12 16.5v4" /></S>
)
export const Globe = (p) => (
  <S {...p}><circle cx="12" cy="12" r="9" /><path d="M3.2 9.5h17.6M3.2 14.5h17.6" /><ellipse cx="12" cy="12" rx="4" ry="9" /></S>
)
export const LogOut = (p) => (
  <S {...p}><path d="M15 4.5h2.5A2.5 2.5 0 0120 7v10a2.5 2.5 0 01-2.5 2.5H15" /><path d="M10 8l-4 4 4 4M6 12h10" /></S>
)
export const Copy = (p) => (
  <S {...p}><rect x="9" y="9" width="12" height="12" rx="2.2" /><path d="M15 6V5.2A2.2 2.2 0 0012.8 3H5.2A2.2 2.2 0 003 5.2v7.6A2.2 2.2 0 005.2 15H6" /></S>
)
export const Check = (p) => <S {...p}><path d="M5 12.8l4.5 4.5L19 7" /></S>
export const X = (p) => <S {...p}><path d="M6 6l12 12M18 6L6 18" /></S>
export const Alert = (p) => (
  <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.2M12 16.3v.2" /></S>
)
export const Info = (p) => (
  <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5M12 7.7v.2" /></S>
)
export const Refresh = (p) => (
  <S {...p}><path d="M20 11.5A8 8 0 006.3 6.3L4 8.5" /><path d="M4 4.5v4h4" /><path d="M4 12.5a8 8 0 0013.7 5.2L20 15.5" /><path d="M20 19.5v-4h-4" /></S>
)
export const Trash = (p) => (
  <S {...p}><path d="M4.5 6.5h15M9.5 6.5V5A1.5 1.5 0 0111 3.5h2A1.5 1.5 0 0114.5 5v1.5" /><path d="M6.5 6.5l.8 12A2 2 0 009.3 20.5h5.4a2 2 0 002-1.9l.8-12" /></S>
)
export const Play = (p) => <S {...p}><path d="M7.5 4.8l11 7.2-11 7.2z" /></S>
export const Key = (p) => (
  <S {...p}><circle cx="8" cy="14" r="4.5" /><path d="M11.3 10.8L20 2.5M17 5.5l2.5 2.5M15 7.5l2.5 2.5" /></S>
)
export const User = (p) => (
  <S {...p}><circle cx="12" cy="8" r="4" /><path d="M4.5 20.5a7.5 7.5 0 0115 0" /></S>
)
export const Users = (p) => (
  <S {...p}><circle cx="9.5" cy="8.5" r="3.5" /><path d="M3 20a6.5 6.5 0 0113 0" /><path d="M16 5.4a3.5 3.5 0 010 6.2M17.5 20a6.6 6.6 0 00-1.3-4" /></S>
)
export const File = (p) => (
  <S {...p}><path d="M14 3H7.5A2.5 2.5 0 005 5.5v13A2.5 2.5 0 007.5 21h9a2.5 2.5 0 002.5-2.5V8z" /><path d="M14 3v5h5" /></S>
)
export const Link = (p) => (
  <S {...p}><path d="M10.5 13.5a4 4 0 006 .5l2-2a4 4 0 00-5.7-5.7l-1.1 1.1" /><path d="M13.5 10.5a4 4 0 00-6-.5l-2 2a4 4 0 005.7 5.7l1.1-1.1" /></S>
)
export const Sparkle = (p) => (
  <S {...p}><path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z" /></S>
)
export const Menu = (p) => <S {...p}><path d="M4 7h16M4 12h16M4 17h16" /></S>
export const Download = (p) => (
  <S {...p}><path d="M12 4v11m0 0l-4-4m4 4l4-4M5 19h14" /></S>
)
export const Printer = (p) => (
  <S {...p}><path d="M7 9V4h10v5M7 19h10v-5H7v5" />
    <path d="M7 14H5a2 2 0 01-2-2v-3a2 2 0 012-2h14a2 2 0 012 2v3a2 2 0 01-2 2h-2" /></S>
)
export const Expand = (p) => (
  <S {...p}><path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5" /></S>
)
export const Collapse = (p) => (
  <S {...p}><path d="M4 9h5V4M20 9h-5V4M4 15h5v5M20 15h-5v5" /></S>
)
export const More = (p) => (
  <S {...p}><circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none" /></S>
)
/* `filled` is the whole point of this one: a star that only changes colour
   reads as a hover state, not as a state you set. */
export const Star = ({ filled = false, ...p }) => (
  <S {...p} fill={filled ? 'currentColor' : 'none'}>
    <path d="M12 3.6l2.6 5.3 5.8.85-4.2 4.1 1 5.75L12 16.9l-5.2 2.7 1-5.75-4.2-4.1 5.8-.85z" />
  </S>
)
export const Graph = (p) => (
  <S {...p}><circle cx="6" cy="7" r="2.4" /><circle cx="18" cy="6" r="2.2" /><circle cx="17" cy="18" r="2.4" /><circle cx="7" cy="17" r="2" /><path d="M8.3 8.2l7 8M8.2 6.6h7.6M6.4 9.4l.4 5.6M9 16.6l5.6.9" /></S>
)
export const Files = (p) => (
  <S {...p}><path d="M3 6.5A1.5 1.5 0 014.5 5h4l1.6 2H19a1.5 1.5 0 011.5 1.5V18a1.5 1.5 0 01-1.5 1.5H4.5A1.5 1.5 0 013 18z" /><path d="M8.5 12h7M8.5 15.2h4.5" /></S>
)
export const Database = (p) => (
  <S {...p}><ellipse cx="12" cy="6" rx="7.5" ry="3" /><path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6" /><path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3" /></S>
)
export const Pencil = (p) => (
  <S {...p}><path d="M4 20l4.5-1.2L20 7.3a2 2 0 00-2.8-2.8L5.7 15.9z" /><path d="M15.5 6.2l2.8 2.8" /></S>
)
export const Eye = (p) => (
  <S {...p}><path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></S>
)
export const Code2 = (p) => (
  <S {...p}><path d="M9 7.5L4 12l5 4.5M15 7.5l5 4.5-5 4.5" /></S>
)
export const Compass = (p) => (
  <S {...p}><circle cx="12" cy="12" r="9" /><path d="M15.6 8.4l-2 5.2-5.2 2 2-5.2z" /></S>
)
export const Flame = (p) => (
  <S {...p}><path d="M12 3s4.8 3.4 4.8 8.2a4.8 4.8 0 01-9.6 0C7.2 9.6 8.6 8 8.6 8s.4 1.8 1.6 2.4C10.7 8.4 12 6.2 12 3z" /><path d="M12 21a4.5 4.5 0 004.8-4.5c0-1.3-.6-2.4-1.4-3.3" /></S>
)
export const Git = (p) => (
  <S {...p}><circle cx="7" cy="6" r="2.3" /><circle cx="7" cy="18" r="2.3" /><circle cx="17" cy="10" r="2.3" /><path d="M7 8.3v7.4M17 12.3c0 3-2.6 3.6-5.4 3.9" /></S>
)
export const PanelLeft = (p) => (
  <S {...p}><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9.5 4v16" /></S>
)

export const CONSOLE_ICON = {
  overview: Overview, ask: Ask, explore: Explore, playground: Playground,
  data: Data, ingest: Ingest, models: Models, people: Users, audit: Audit,
}
