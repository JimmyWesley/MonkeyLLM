# The MonkeyLLM Handbook

English · [Português](../pt/README.md) · [Español](../es/README.md)

## The pitch

This deployment keeps a **knowledge forest**: curated markdown nodes, each
carrying a passport of title, summary, tags and typed edges, plus the
lightweight indexes that make them findable. An AI does not get handed a
retrieval dump it *navigates*: drops in through search, walks the edges,
reads exactly the node it needs, and plants what it learns as a new node.
The forest remembers across conversations, across agents, for as long as
you keep it growing.

The first time you sign in, the console says it plainly: **"A brain your
AIs can grow. The console is a window. The forest behind it is the
product."** That sentence is the whole architecture. Keep it in mind on
every page of this handbook nothing you see in the browser is the thing
itself; it is a view onto a forest that your own agents read and feed
over MCP.

![The first-access presentation: a brain your AIs can grow](../assets/welcome.png)

Around the forest sits the **Station**, the self-hostable host: one
container, REST under `/v1`, MCP under `/mcp`, identity, per-forest
policy and an audit trail so a forest can be a governed shared asset
instead of a personal directory. The Station also serves the **Studio**,
the web console where people watch, govern and teach the forest: ask
grounded questions, walk the tree, ingest documents, grant access, bind
models.

The real audience, though, is your AIs. Claude Code or any MCP-capable
agent plugs into the Station and gains the forest's tools recall,
navigation, SQL over datasets, planting. What one agent saves today,
another recalls next month; corrections a person makes in the console
are what the next agent reads. The forest is the shared memory; the
console and the agents are two hands feeding the same brain.

When you open a forest, the Overview console orients you: how many nodes,
branches and datasets your key can reach, where to start, and what you
may do here. Everything it counts is reachable by any agent you connect
— that symmetry is the point.

![The Overview console: what is in this forest, and what you may do here](../assets/overview.png)

> **Note** Everything the Studio does travels through the same routes
> any client can call; there is no privileged side-channel. Whatever the
> console shows you, an API client holding the same key could fetch too.

## How the pieces fit

| Piece | One line |
|---|---|
| **Forest** | The product: curated markdown nodes with passports, lightweight indexes and their own git history the knowledge itself. |
| **Vine primitives** | The ten MCP tools an agent navigates with `locate`, `look`, `move`, `pick`, `scan`, `sniff`, `query` to read; `plant`, `graft`, `tend` to write plus composites like `harvest` and `answer`. |
| **Station** | The self-hostable host: REST `/v1`, MCP `/mcp`, identity, per-forest policy and audit wrapped around the untouched engine. |
| **Studio** | The web console the Station serves how people watch, govern and teach the forest. A window, never the product. |
| **Clipper** | A browser extension that clips the page you are reading into a forest article or selection as markdown, screenshot as a media node. |
| **Skills** | The console that hands your agent a small instruction file teaching it to use this forest as its persistent memory. |

## Table of contents

| Page | After it, you can |
|---|---|
| [Install & deploy](./install.md) | Bring a Station up Docker Compose or from source and keep everything worth keeping in named volumes. |
| [First access](./first-access.md) | Sign in for the first time, claim the deployment, and understand exactly what your key can reach. |
| [Using the forest](./using.md) | Ask questions that arrive with their sources, walk the tree in Explore, and query datasets in Data. |
| [Feeding it](./feeding.md) | Upload documents, adopt whole folders and clip pages from your browser and let the Gardener turn them into curated, findable knowledge. |
| [Connecting your AI](./connecting-ai.md) | Pair a key of your own, point Claude Code or any MCP agent at this Station, and hand it the skill that makes the forest its memory. |
| [Managing & governing](./managing.md) | Grant and scope access, bind models, read the audit, and keep the forest healthy over time. |

## If you only read one page

Read [Connecting your AI](./connecting-ai.md). The console can ask, browse
and ingest on its own, but the forest is built to be read and fed by your
own agents a forest only ever touched through the window is a brain
nobody is growing. That page takes you the whole way in three steps: pair
a key that is yours (it can only narrow your access, never add to it),
register the Station as an MCP server, and hand your agent the skill file
the Studio generates for this exact deployment. Every other page deepens
what that one starts.
