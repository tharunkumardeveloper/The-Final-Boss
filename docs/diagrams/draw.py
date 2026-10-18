"""Hand-laid horizontal diagrams for the README, as SVG in a light and a dark theme (GitHub picks by colour scheme).
Run from the repo root: python docs/diagrams/draw.py  ->  docs/diagrams/{architecture,idea,location}-{light,dark}.svg"""
from html import escape
from pathlib import Path

OUT = Path(__file__).parent
FONT = "Segoe UI, -apple-system, Helvetica, Arial, sans-serif"
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#0f1720", "sub": "#52606d", "line": "#8a97a6", "group": "#f4f6f8", "groupline": "#d6dde4",
              "box": "#ffffff", "boxline": "#c9d2db", "teal": "#14a39a", "tealbg": "#e3f6f4", "amber": "#b7791f",
              "amberbg": "#fdf3e1", "blue": "#2563eb", "bluebg": "#e8efff", "violet": "#7c5cc4", "violetbg": "#f0ebfb",
              "green": "#268554", "greenbg": "#e7f5ec", "labelbg": "#ffffff"},
    "dark": {"bg": "#0d1117", "ink": "#e6edf3", "sub": "#9aa7b4", "line": "#6e7c8a", "group": "#161b22", "groupline": "#30363d",
             "box": "#0d1117", "boxline": "#3a434d", "teal": "#2dd4bf", "tealbg": "#0f2f2c", "amber": "#f0b45a",
             "amberbg": "#2d2412", "blue": "#7aa2ff", "bluebg": "#16213d", "violet": "#b39cff", "violetbg": "#231c3a",
             "green": "#4ade80", "greenbg": "#10291a", "labelbg": "#0d1117"},
}


class Svg:
    def __init__(self, w, h, theme):
        self.w, self.h, self.t, self.parts = w, h, THEMES[theme], []
        self.boxes = {}

    def group(self, x, y, w, h, title, tone=None):
        t = self.t
        fill, stroke = (t[tone + "bg"], t[tone]) if tone else (t["group"], t["groupline"])
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        self.parts.append(f'<text x="{x + 22}" y="{y + 34}" font-size="15" font-weight="700" letter-spacing="1.6" '
                          f'fill="{t[tone] if tone else t["sub"]}">{escape(title.upper())}</text>')

    def box(self, key, x, y, w, h, title, sub=(), tone=None, size=20):
        t = self.t
        fill, stroke = (t[tone + "bg"], t[tone]) if tone else (t["box"], t["boxline"])
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        lines = [(title, size, 650, t["ink"])] + [(s, size - 4, 400, t["sub"]) for s in sub]
        total = sum(s * 1.32 for _, s, _, _ in lines)
        cy = y + h / 2 - total / 2
        for text, s, wt, col in lines:
            cy += s * 1.32
            self.parts.append(f'<text x="{x + w / 2}" y="{cy - s * 0.32:.1f}" text-anchor="middle" font-size="{s}" '
                              f'font-weight="{wt}" fill="{col}">{escape(text)}</text>')
        self.boxes[key] = (x, y, w, h)

    def diamond(self, key, cx, cy, w, h, title, sub=()):
        t = self.t
        pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
        self.parts.append(f'<polygon points="{pts}" fill="{t["box"]}" stroke="{t["boxline"]}" stroke-width="1.6"/>')
        lines = [(title, 18, 650, t["ink"])] + [(s, 15, 400, t["sub"]) for s in sub]
        total = sum(s * 1.3 for _, s, _, _ in lines)
        y = cy - total / 2
        for text, s, wt, col in lines:
            y += s * 1.3
            self.parts.append(f'<text x="{cx}" y="{y - s * 0.3:.1f}" text-anchor="middle" font-size="{s}" font-weight="{wt}" '
                              f'fill="{col}">{escape(text)}</text>')
        self.boxes[key] = (cx - w / 2, cy - h / 2, w, h)

    def side(self, key, where, at=0.5):
        x, y, w, h = self.boxes[key]
        return {"r": (x + w, y + h * at), "l": (x, y + h * at), "t": (x + w * at, y), "b": (x + w * at, y + h)}[where]

    def arrow(self, a, b, label=None, both=False, tone=None, dashed=False, label_at=0.5, label_dy=-12, bend="h"):
        t = self.t
        col = t[tone] if tone else t["line"]
        (x1, y1), (x2, y2) = a, b
        if bend == "h":  # leave and arrive horizontally
            mx = (x1 + x2) / 2
            d = f"M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}"
        else:  # leave and arrive vertically
            my = (y1 + y2) / 2
            d = f"M{x1},{y1} C{x1},{my} {x2},{my} {x2},{y2}"
        mid = "url(#a-%s)" % (tone or "line")
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.2"{dash} marker-end="{mid}"'
                          + (f' marker-start="url(#s-{tone or "line"})"' if both else "") + "/>")
        if label:
            lx, ly = x1 + (x2 - x1) * label_at, y1 + (y2 - y1) * label_at + label_dy
            w = 9.2 * len(label) + 16
            self.parts.append(f'<rect x="{lx - w / 2:.1f}" y="{ly - 16:.1f}" width="{w:.1f}" height="24" rx="12" fill="{t["labelbg"]}" '
                              f'stroke="{col}" stroke-width="1"/>')
            self.parts.append(f'<text x="{lx:.1f}" y="{ly + 1:.1f}" text-anchor="middle" font-size="15" font-weight="600" '
                              f'fill="{col}">{escape(label)}</text>')

    def path(self, d, tone=None, end=False):
        col = self.t[tone] if tone else self.t["line"]
        self.parts.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.2"'
                          + (f' marker-end="url(#a-{tone or "line"})"' if end else "") + "/>")

    def text(self, x, y, s, size=16, anchor="start", tone="sub", weight=400):
        self.parts.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" '
                          f'fill="{self.t[tone]}">{escape(s)}</text>')

    def render(self):
        t = self.t
        marks = "".join(
            f'<marker id="a-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{t[k]}"/></marker>'
            f'<marker id="s-{k}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{t[k]}"/></marker>'
            for k in ("line", "teal", "amber", "blue", "violet", "green"))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
                f'font-family="{FONT}"><defs>{marks}</defs><rect width="{self.w}" height="{self.h}" fill="{t["bg"]}"/>'
                + "".join(self.parts) + "</svg>\n")


def architecture(theme):
    s = Svg(1560, 884, theme)
    s.group(20, 20, 250, 720, "People")
    s.box("cust", 42, 120, 206, 96, "Customer", ["chats in plain words"])
    s.box("staff", 42, 300, 206, 96, "Staff", ["watches and tests"])
    s.box("claude", 42, 560, 206, 110, "Claude or any", ["MCP client", "a fourth agent"], tone="violet")

    s.group(320, 20, 260, 720, "Web · Vercel")
    s.box("site", 342, 120, 216, 96, "Customer site", ["chat · tickets · memory"], tone="blue")
    s.box("console", 342, 300, 216, 96, "Staff console", ["graph · lab · benchmark"], tone="blue")
    s.text(450, 450, "Both talk to the API over", 15, "middle", "ink", 600)
    s.text(450, 474, "HTTPS and one live WebSocket", 15, "middle", "ink", 600)
    s.text(450, 520, "React · TypeScript · Vite", 15, "middle")
    s.text(450, 544, "Tailwind · Framer Motion", 15, "middle")

    s.group(630, 20, 380, 720, "API · FastAPI on Render")
    s.box("api", 652, 74, 336, 66, "REST + live WebSocket", ["api/main.py"])
    s.box("intake", 652, 160, 336, 70, "Mr.Fix-It · intake", ["facts, tickets, handoffs"], tone="teal")
    s.box("resolver", 652, 246, 336, 70, "Resolver + Network lab", ["measures, fixes, re-measures"], tone="teal")
    s.box("noc", 652, 332, 336, 70, "Network Ops", ["traversal, warnings first"], tone="teal")
    s.box("sim", 652, 418, 336, 64, "Persona simulator", ["weeks in minutes"])
    s.box("mcp", 652, 566, 336, 76, "MCP server", ["mcp_server.py · typed tools"], tone="violet")
    s.box("embed", 652, 660, 336, 60, "fastembed · local", ["embeddings, no API call"])

    s.box("groq", 1062, 34, 150, 82, "Groq", ["gpt-oss · qwen"], size=19)
    s.box("gemini", 1222, 34, 150, 82, "Gemini", ["fallback"], size=19)
    s.box("geo", 1382, 34, 156, 82, "OpenCage", ["addresses"], size=19)

    s.text(1300, 146, "models and geocoding the agents call", 15, "middle")
    s.group(1060, 166, 480, 574, "Memory · FalkorDB Cloud", tone="teal")
    s.box("graphs", 1082, 214, 436, 80, "One graph per region", ["mem:pml · mem:pml-eu · mem:pml-na · …"])
    s.box("mem", 1082, 306, 436, 118, "Episodes · Facts · Entities", ["two clocks on every fact, nothing overwritten",
                                                                      "tickets and handoffs as graph state",
                                                                      "fixes as procedure paths"])
    s.box("net", 1082, 436, 436, 80, "The network as a graph", ["core → hub → exchange → cabinet → home"])
    s.box("algo", 1082, 528, 436, 104, "Cypher · vector + full-text indexes", ["algo.maxFlow · algo.MSF · betweenness",
                                                                                 "PageRank · label propagation · GRAPH.COPY"])
    s.box("chaos", 1082, 644, 436, 74, "chaos:pml", ["the lab's hidden fault truth"])

    s.arrow(s.side("cust", "r"), s.side("site", "l"), tone="blue")
    s.arrow(s.side("staff", "r"), s.side("console", "l"), tone="blue")
    s.arrow(s.side("site", "r"), s.side("api", "l", 0.4), both=True, tone="blue")
    s.arrow(s.side("console", "r"), s.side("api", "l", 0.75), both=True, tone="blue")
    s.arrow(s.side("claude", "r"), s.side("mcp", "l"), "MCP", tone="violet", label_at=0.5, label_dy=-14)
    s.arrow(s.side("api", "r", 0.5), s.side("groq", "l", 0.6), tone="amber")
    # every agent reads and writes the same graph: one bracket from the three agents into memory
    bx = 1024
    for k in ("intake", "resolver", "noc"):
        x, y = s.side(k, "r")
        s.path(f"M{x},{y} H{bx}", tone="teal")
    s.path(f"M{bx},{s.side('intake', 'r')[1]} V{s.side('noc', 'r')[1]}", tone="teal")
    s.arrow((bx, s.side("resolver", "r")[1]), s.side("mem", "l", 0.4), "Cypher", tone="teal", label_at=0.5, label_dy=-16)
    s.arrow(s.side("mcp", "r", 0.4), s.side("algo", "l", 0.5), tone="teal", both=True)
    s.text(820, 528, "The agents never message each other:", 16, "middle", "ink", 600)
    s.text(820, 552, "every handoff is state in the graph.", 16, "middle", "sub")
    # the work the graph does (the hackathon's five), as one band under the whole system
    s.group(20, 760, 1520, 110, "Work the graph does", tone="teal")
    jobs = ["Follows connections across data", "Remembers across sessions", "Shares state between agents",
            "Connects people, cases and decisions", "Shows the path behind every answer"]
    x, gap = 42, 12
    width = (1520 - 44 - gap * (len(jobs) - 1)) / len(jobs)
    for j in jobs:
        s.box("job:" + j, x, 808, width, 46, j, size=15)
        x += width + gap
    return s.render()


def idea(theme):
    s = Svg(1400, 470, theme)
    s.box("cust", 30, 175, 190, 96, "Customer", ["chats"])
    s.box("intake", 290, 175, 230, 96, "Mr.Fix-It", ["intake agent"], tone="teal")
    s.box("graph", 600, 120, 300, 206, "FalkorDB", ["one graph per tenant", "", "who wrote it · when it was true",
                                                    "what it replaced · the path"], tone="teal", size=24)
    s.box("resolver", 990, 40, 260, 86, "Resolver", ["reads · acts · re-measures"], tone="teal")
    s.box("noc", 990, 160, 260, 86, "Network Ops", ["traversal · warnings"], tone="teal")
    s.box("mcp", 990, 280, 260, 86, "Claude / any MCP client", ["a fourth agent"], tone="violet")
    s.box("console", 600, 384, 300, 66, "Staff console", ["the graph, live"], tone="blue")
    s.arrow(s.side("cust", "r"), s.side("intake", "l"), "chat")
    s.arrow(s.side("intake", "r"), s.side("graph", "l"), "facts · ticket", tone="teal", label_dy=-16)
    for k in ("resolver", "noc"):
        s.arrow(s.side(k, "l"), s.side("graph", "r", 0.32 if k == "resolver" else 0.5), both=True, tone="teal")
    s.arrow(s.side("mcp", "l"), s.side("graph", "r", 0.72), "MCP", both=True, tone="violet", label_at=0.4, label_dy=-14)
    s.arrow(s.side("graph", "b"), s.side("console", "t"), tone="blue", bend="v")
    s.text(700, 30, "The agents never message each other.", 17, "middle", "ink", 600)
    return s.render()


def location(theme):
    s = Svg(1500, 420, theme)
    s.box("addr", 24, 60, 220, 96, "Any address", ["suburb · PIN code · landmark"])
    s.diamond("own", 430, 108, 280, 150, "WiFight's own list", ["199 cities · 1,118 areas"])
    s.diamond("geon", 800, 108, 260, 150, "Offline town list", ["GeoNames"])
    s.box("oc", 1040, 60, 210, 96, "OpenCage", ["geocoding"], tone="amber")
    s.box("near", 330, 290, 560, 88, "Nearest city & area we serve", ["matched by distance"], tone="teal", size=21)
    s.box("desk", 1010, 290, 466, 88, "Right desk · line · resolver", ["and the Network lab follow"], tone="teal")
    s.arrow(s.side("addr", "r"), s.side("own", "l"))
    s.arrow(s.side("own", "r"), s.side("geon", "l"), "not listed", label_dy=-14)
    s.arrow(s.side("geon", "r"), s.side("oc", "l"), "unknown or ambiguous", label_dy=-14)
    s.arrow(s.side("own", "b"), s.side("near", "t", 0.18), "found", tone="teal", bend="v", label_dy=0)
    s.arrow(s.side("geon", "b"), s.side("near", "t", 0.84), "found", tone="teal", bend="v", label_dy=0)
    s.arrow(s.side("oc", "b"), s.side("near", "r", 0.3), tone="teal", bend="v")
    s.arrow(s.side("near", "r", 0.7), s.side("desk", "l", 0.7), tone="teal")
    return s.render()


def datamodel(theme):
    """The graph as it is (read from the live India graph): five bands, by kind of memory, left to right."""
    s = Svg(1640, 1210, theme)
    s.group(20, 20, 1600, 196, "Episodic memory · what was said", tone="teal")
    s.box("agent", 60, 92, 220, 76, "Agent", ["intake · resolver · noc · mcp"])
    s.box("ep", 400, 92, 260, 76, "Episode", ["a message, reply, tool reading", "or note, with its time"], tone="teal")
    s.box("ses", 780, 92, 240, 76, "Session", ["HAS_SESSION from the customer", "FOLLOWED_BY the next one"])
    for i, line in enumerate(["Every message is kept exactly as it was said.",
                              "Kinds: CustomerMessage · AgentReply · ToolResult · InternalNote",
                              "A vector index on the text: recall by meaning"]):
        s.text(1080, 112 + i * 26, line, 16, tone="ink" if i == 0 else "sub", weight=600 if i == 0 else 400)

    s.group(20, 236, 1600, 228, "Semantic memory · what is true, with two clocks", tone="green")
    s.box("conf", 60, 318, 220, 80, "Conflict", ["two agents disagree;", "both claims are kept"], tone="amber")
    s.box("fact", 400, 290, 280, 132, "Fact", ["subject · predicate · object", "valid_from → valid_to  (world)",
                                              "recorded_at → expired_at  (on file)", "SUPERSEDES the one it replaced"],
          tone="green")
    s.box("cust", 790, 318, 210, 80, "Customer", ["an Entity"], tone="green")
    s.box("things", 1100, 290, 500, 132, "City · Area · Plan · Device · Phone · …", ["one typed edge per current fact:",
                                                                                   "LIVES_IN · ON_PLAN · OWNS_DEVICE · PHONE · …",
                                                                                   "a fact that ends becomes a WAS edge"])
    s.group(20, 484, 1600, 248, "Procedural memory · how a case is handled", tone="amber")
    s.box("tech", 60, 584, 200, 76, "Technician", ["BASED_IN a city"])
    s.box("visit", 330, 584, 200, 76, "TechVisit", ["a home visit"])
    s.box("ticket", 620, 556, 250, 132, "Ticket", ["HANDED_OFF / PICKED_UP", "by agents · RAISED_IN a session",
                                                  "status · priority · ESCALATED"], tone="amber")
    s.box("issue", 1080, 528, 220, 70, "Issue", ["what went wrong"])
    s.box("fix", 1080, 640, 220, 70, "Fix", ["tried; FIXED_BY = it worked"])
    s.box("proc", 1380, 528, 220, 70, "Procedure", ["LEARNED_FROM a ticket"], tone="amber")
    s.box("step", 1380, 640, 220, 70, "ProcStep", ["FIRST, then NEXT"])

    s.group(20, 752, 1600, 200, "The network · the line a customer is on")
    s.box("bb", 60, 832, 190, 76, "Backbone", ["core"])
    s.box("pop", 330, 832, 190, 76, "Pop", ["city hub"])
    s.box("olt", 860, 820, 240, 100, "Olt", ["the exchange", "UPLINK to the hub"], tone="blue")
    s.box("split", 1170, 832, 190, 76, "Splitter", ["street cabinet"])
    s.box("ont", 1410, 832, 190, 76, "Ont", ["the box at home", "(HAS_ONT)"])

    s.group(20, 972, 1600, 218, "World and catalogue")
    s.box("out", 60, 1036, 190, 64, "Outage", [], tone="amber")
    s.box("city", 330, 1036, 190, 64, "City", [])
    s.box("country", 600, 1036, 190, 64, "Country", [])
    s.box("cat", 870, 1024, 260, 88, "Plan · Service · Addon", ["prices per country"])
    s.box("faq", 1200, 1036, 150, 64, "Faq", [])
    s.box("play", 1400, 1024, 200, 88, "Playbook", ["FIRST_STEP → Step", "FOR_ISSUE · FOR_ROUTER"])
    s.box("area", 60, 1120, 190, 56, "Area", [])

    # episodic
    s.arrow(s.side("agent", "r"), s.side("ep", "l"), "WROTE", tone="teal")
    s.arrow(s.side("ep", "r"), s.side("ses", "l"), "IN", tone="teal")
    # episodic -> semantic
    s.arrow(s.side("ep", "b", 0.4), s.side("fact", "t", 0.4), "DERIVED · RETIRED", tone="green", bend="v", label_dy=0)
    s.arrow(s.side("ep", "b", 0.85), s.side("cust", "t", 0.3), "MENTIONS", tone="teal", bend="v", label_dy=0)
    s.arrow(s.side("agent", "b", 0.5), s.side("fact", "l", 0.25), "CONSULTED · WRITTEN_BY", both=True, bend="v",
            label_at=0.35, label_dy=0)
    # semantic
    s.arrow(s.side("conf", "r"), s.side("fact", "l", 0.72), "BETWEEN", tone="amber", label_dy=-14)
    s.arrow(s.side("fact", "r"), s.side("cust", "l"), "ABOUT", tone="green")
    s.arrow(s.side("cust", "r"), s.side("things", "l"), "typed edges", tone="green")
    # semantic -> procedural
    s.arrow(s.side("cust", "b", 0.25), s.side("ticket", "t", 0.65), "HAS_TICKET", tone="amber", bend="v", label_dy=0)
    # procedural
    s.arrow(s.side("tech", "r"), s.side("visit", "l"), "VISITS")
    s.arrow(s.side("visit", "r"), s.side("ticket", "l", 0.6), "FOR_TICKET", label_dy=-14)
    s.arrow(s.side("ticket", "r", 0.25), s.side("issue", "l"), "TICKET_ABOUT", tone="amber", label_at=0.3, label_dy=-14)
    s.arrow(s.side("ticket", "r", 0.78), s.side("fix", "l"), "TRIED_FIX", tone="amber", label_at=0.3, label_dy=16)
    s.arrow(s.side("fix", "t"), s.side("issue", "b"), "RESOLVES", tone="amber", bend="v", label_dy=0)
    s.arrow(s.side("proc", "l"), s.side("issue", "r"), "RESOLVES", tone="amber", label_dy=-14)
    s.arrow(s.side("proc", "b"), s.side("step", "t"), "FIRST", tone="amber", bend="v", label_dy=0)
    # semantic -> network
    s.arrow(s.side("cust", "b", 0.95), s.side("olt", "t", 0.55), "CONNECTED_VIA", tone="blue", bend="v", label_at=0.9, label_dy=0)
    # network
    s.arrow(s.side("olt", "l", 0.5), s.side("pop", "r"), "UPLINK", tone="blue")
    s.arrow(s.side("pop", "l"), s.side("bb", "r"), "UPLINK", tone="blue")
    s.arrow(s.side("split", "l"), s.side("olt", "r", 0.5), "PON", tone="blue")
    s.arrow(s.side("split", "r"), s.side("ont", "l"), "DROP", tone="blue")
    # world and catalogue
    s.arrow(s.side("out", "r"), s.side("city", "l"), "AFFECTS", tone="amber")
    s.arrow(s.side("area", "r"), s.side("city", "b", 0.3), "IN_CITY", bend="h", label_at=0.45, label_dy=8)
    s.arrow(s.side("city", "r"), s.side("country", "l"), "IN_COUNTRY")
    s.arrow(s.side("cat", "l"), s.side("country", "r"), "PRICED_IN")
    s.arrow(s.side("faq", "l"), s.side("cat", "r"), "EXPLAINS")
    return s.render()


if __name__ == "__main__":
    for name, fn in (("architecture", architecture), ("idea", idea), ("location", location), ("data-model", datamodel)):
        for theme in THEMES:
            (OUT / f"{name}-{theme}.svg").write_text(fn(theme), encoding="utf-8")
            print(f"{name}-{theme}.svg")
