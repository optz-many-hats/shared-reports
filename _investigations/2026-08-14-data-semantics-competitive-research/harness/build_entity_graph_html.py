#!/usr/bin/env python3
"""Build entity-graph.html with all data (graph + topics) embedded.

Reads graph_with_topics.json and topics_data.json, then generates the
complete HTML file with Cytoscape.js visualisation, topic tabs, topic
detail sidebar, node detail sidebar, search, filters, and layout toggles.

Usage:
    python3 harness/build_entity_graph_html.py
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent / "output"
GRAPH_PATH = BASE / "graph_with_topics.json"
TOPICS_PATH = BASE / "topics_data.json"
OUT_HTML = Path(__file__).resolve().parent.parent / "entity-graph.html"


def build_topics_for_embed(topics_raw: dict) -> dict:
    """Transform raw topic files into the compact format for embedding.

    Each topic gets: name, description, member_ids, concepts (with label+description),
    business_rules (step 6), disambiguation (step 7), expansion_policy (step 8).
    """
    result = {}
    for slug, t in topics_raw.items():
        cs = t.get("checklist_state", {})
        name = t.get("name", slug)
        description = cs.get("1", {}).get("answer", "")

        # Collect member IDs from steps 2-5 and concept_cluster
        member_ids = set()
        cc = t.get("concept_cluster", {})
        member_ids.update(cc.get("concept_ids", []))
        for step in ("2", "3", "4", "5"):
            for item in cs.get(step, {}).get("selected", []):
                member_ids.add(item["id"])

        # Concepts (step 2)
        concepts = []
        for item in cs.get("2", {}).get("selected", []):
            concepts.append({
                "label": item.get("label", ""),
                "description": item.get("description", ""),
            })

        # Business rules (step 6)
        business_rules = []
        for item in cs.get("6", {}).get("selected", []):
            business_rules.append({
                "term": item.get("label", ""),
                "definition": item.get("description", ""),
            })

        # Disambiguation (step 7)
        disambiguation = []
        for item in cs.get("7", {}).get("selected", []):
            disambiguation.append({
                "term": item.get("label", ""),
                "meaning": item.get("description", ""),
            })

        # Expansion policy (step 8)
        expansion_policy = ""
        step8 = cs.get("8", {}).get("selected", [])
        if step8:
            expansion_policy = step8[0].get("label", "")
            if step8[0].get("description"):
                expansion_policy += " - " + step8[0]["description"]

        # Datasets (step 3)
        datasets_count = len(cs.get("3", {}).get("selected", []))
        # Metrics (step 4)
        metrics_count = len(cs.get("4", {}).get("selected", []))
        # Events (step 5)
        events_count = len(cs.get("5", {}).get("selected", []))

        result[slug] = {
            "name": name,
            "description": description,
            "member_ids": sorted(member_ids),
            "concepts": concepts,
            "business_rules": business_rules,
            "disambiguation": disambiguation,
            "expansion_policy": expansion_policy,
            "disambig_count": len(disambiguation),
            "policy": expansion_policy.split(" ")[0].lower() if expansion_policy else "",
        }

    return result


def generate_html(graph_json: str, topics_json: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Opti on Opti - Full Entity & Concept Graph</title>
  <script src="https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js"></script>
  <script src="https://unpkg.com/layout-base@2.0.1/layout-base.js"></script>
  <script src="https://unpkg.com/cose-base@2.2.0/cose-base.js"></script>
  <script src="https://unpkg.com/cytoscape-fcose@2.2.0/cytoscape-fcose.js"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e1e4e8; }}

    .header {{ padding: 14px 24px; border-bottom: 1px solid #21262d; display: flex; align-items: center; gap: 16px; }}
    .header h1 {{ font-size: 18px; font-weight: 600; color: #f0f6fc; }}
    .header .subtitle {{ font-size: 13px; color: #8b949e; }}
    .header .badge {{ font-size: 11px; background: #388bfd33; color: #58a6ff; padding: 2px 8px; border-radius: 10px; }}

    /* Topic tabs */
    .topic-tabs {{ display: flex; padding: 0 24px; border-bottom: 1px solid #21262d; overflow-x: auto; flex-wrap: nowrap; gap: 0; }}
    .topic-tab {{ padding: 10px 14px; font-size: 12px; color: #8b949e; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.15s; user-select: none; white-space: nowrap; }}
    .topic-tab:hover {{ color: #e1e4e8; }}
    .topic-tab.active {{ color: #f778ba; border-bottom-color: #f778ba; }}
    .topic-tab .count {{ font-size: 10px; color: #484f58; margin-left: 4px; }}
    .topic-tab.active .count {{ color: #f778ba; }}

    /* Filter bar */
    .filter-bar {{ display: flex; padding: 6px 24px; border-bottom: 1px solid #21262d; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .filter-btn {{ font-size: 11px; padding: 3px 9px; border-radius: 12px; border: 1px solid #30363d; background: transparent; cursor: pointer; transition: all 0.15s; user-select: none; }}
    .filter-btn.active {{ border-color: currentColor; }}
    .filter-btn[data-ntype="concept"] {{ color: #58a6ff; }}
    .filter-btn[data-ntype="concept"].active {{ background: rgba(88,166,255,0.15); }}
    .filter-btn[data-ntype="dataset"] {{ color: #7ee787; }}
    .filter-btn[data-ntype="dataset"].active {{ background: rgba(126,231,135,0.15); }}
    .filter-btn[data-ntype="metric"] {{ color: #d2a8ff; }}
    .filter-btn[data-ntype="metric"].active {{ background: rgba(210,168,255,0.15); }}
    .filter-btn[data-ntype="column"] {{ color: #ffa657; }}
    .filter-btn[data-ntype="column"].active {{ background: rgba(255,166,87,0.15); }}
    .filter-btn[data-ntype="event"] {{ color: #ff7b72; }}
    .filter-btn[data-ntype="event"].active {{ background: rgba(255,123,114,0.15); }}
    .filter-label {{ font-size: 11px; color: #8b949e; margin-right: 4px; }}
    .search-box {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #e1e4e8; font-size: 12px; padding: 3px 10px; width: 220px; outline: none; margin-left: auto; }}
    .search-box:focus {{ border-color: #58a6ff; }}
    .search-box::placeholder {{ color: #484f58; }}

    .scope-btn {{ font-size: 11px; padding: 3px 9px; border-radius: 12px; border: 1px solid #30363d; background: transparent; color: #8b949e; cursor: pointer; transition: all 0.15s; user-select: none; }}
    .scope-btn.active {{ border-color: #8b949e; background: rgba(139,148,158,0.15); color: #e1e4e8; }}

    .view-toggle {{ display: flex; gap: 4px; margin-left: 12px; }}
    .view-btn {{ font-size: 11px; padding: 3px 9px; border-radius: 4px; border: 1px solid #30363d; background: transparent; color: #8b949e; cursor: pointer; }}
    .view-btn.active {{ background: #21262d; color: #e1e4e8; border-color: #484f58; }}

    .main {{ display: flex; height: calc(100vh - 130px); }}
    #cy {{ flex: 1; min-height: 400px; }}

    /* Sidebar */
    .sidebar {{ width: 380px; border-left: 1px solid #21262d; overflow-y: auto; padding: 14px; flex-shrink: 0; }}

    /* Topic detail panel */
    .topic-detail {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 12px; margin-bottom: 14px; display: none; }}
    .topic-detail.visible {{ display: block; }}
    .topic-detail h3 {{ font-size: 14px; font-weight: 600; color: #f778ba; margin-bottom: 6px; }}
    .topic-detail .topic-stat {{ font-size: 12px; color: #8b949e; padding: 2px 0; }}
    .topic-detail .topic-stat span {{ color: #e1e4e8; font-weight: 500; }}
    .topic-detail .topic-desc {{ font-size: 12px; color: #8b949e; line-height: 1.5; margin: 6px 0 10px; }}
    .topic-section {{ margin-top: 10px; }}
    .topic-section-title {{ font-size: 11px; font-weight: 600; color: #f0f6fc; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; cursor: pointer; user-select: none; }}
    .topic-section-title:hover {{ color: #58a6ff; }}
    .topic-section-title::before {{ content: '\\25B6'; font-size: 8px; margin-right: 4px; display: inline-block; transition: transform 0.15s; }}
    .topic-section-title.open::before {{ transform: rotate(90deg); }}
    .topic-section-body {{ display: none; margin-left: 2px; }}
    .topic-section-body.open {{ display: block; }}
    .topic-concept-item {{ padding: 4px 0; border-bottom: 1px solid #21262d; }}
    .topic-concept-item:last-child {{ border-bottom: none; }}
    .topic-concept-name {{ font-size: 12px; color: #58a6ff; font-weight: 500; }}
    .topic-concept-desc {{ font-size: 11px; color: #8b949e; line-height: 1.4; margin-top: 2px; }}
    .topic-rule {{ padding: 4px 0; border-bottom: 1px solid #21262d; }}
    .topic-rule:last-child {{ border-bottom: none; }}
    .topic-rule-term {{ font-size: 11px; color: #e1e4e8; font-weight: 500; }}
    .topic-rule-def {{ font-size: 11px; color: #8b949e; line-height: 1.4; margin-top: 1px; }}
    .topic-policy-label {{ font-size: 12px; color: #7ee787; font-weight: 500; margin-top: 6px; }}

    /* Node detail panel */
    .node-detail {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 12px; margin-bottom: 14px; display: none; }}
    .node-detail.visible {{ display: block; }}
    .node-detail h3 {{ font-size: 14px; font-weight: 600; color: #f0f6fc; margin-bottom: 4px; word-break: break-word; }}
    .node-detail .type-badge {{ display: inline-block; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 2px 6px; border-radius: 4px; margin-bottom: 6px; }}
    .node-detail .desc {{ font-size: 12px; color: #c9d1d9; line-height: 1.6; margin: 8px 0; }}
    .node-detail .meta {{ font-size: 11px; color: #484f58; margin-top: 4px; }}
    .node-detail .topic-tags {{ margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }}
    .node-detail .topic-tag {{ font-size: 10px; background: #f778ba22; color: #f778ba; padding: 2px 6px; border-radius: 4px; cursor: pointer; }}
    .node-detail .topic-tag:hover {{ background: #f778ba44; }}
    .node-detail .edges-list {{ margin-top: 10px; font-size: 11px; color: #8b949e; max-height: 300px; overflow-y: auto; }}
    .node-detail .edges-list div {{ padding: 3px 0; cursor: pointer; border-bottom: 1px solid #21262d; }}
    .node-detail .edges-list div:last-child {{ border-bottom: none; }}
    .node-detail .edges-list div:hover {{ color: #58a6ff; }}
    .edge-pred {{ font-weight: 600; color: #e1e4e8; font-size: 10px; text-transform: uppercase; letter-spacing: 0.3px; }}

    /* Layout & legend */
    .layout-btns {{ display: flex; gap: 0; margin-bottom: 14px; }}
    .layout-btn {{ font-size: 11px; padding: 4px 10px; border: 1px solid #30363d; background: transparent; color: #8b949e; cursor: pointer; }}
    .layout-btn:first-child {{ border-radius: 6px 0 0 6px; }}
    .layout-btn:last-child {{ border-radius: 0 6px 6px 0; border-left: none; }}
    .layout-btn.active {{ background: #21262d; color: #58a6ff; border-color: #58a6ff; }}

    .legend {{ margin-bottom: 16px; }}
    .legend-item {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 11px; color: #8b949e; }}
    .legend-dot {{ width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }}
    .legend-line {{ width: 18px; height: 0; flex-shrink: 0; }}

    /* Stats */
    .stats {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 10px; margin-bottom: 14px; }}
    .stats-row {{ display: flex; justify-content: space-between; padding: 2px 0; font-size: 12px; }}
    .stats-label {{ color: #8b949e; }}
    .stats-value {{ color: #e1e4e8; font-weight: 500; }}

    /* List view */
    .entity-list-view {{ flex: 1; overflow-y: auto; padding: 14px; display: none; }}
    .entity-item {{ padding: 6px 8px; border-bottom: 1px solid #21262d; cursor: pointer; }}
    .entity-item:hover {{ background: #1c2128; }}
    .entity-item .name {{ font-size: 12px; color: #e1e4e8; font-weight: 500; }}
    .entity-item .short-desc {{ font-size: 11px; color: #8b949e; margin-top: 2px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
    .type-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }}
    .dot-concept {{ background: #58a6ff; }}
    .dot-dataset {{ background: #7ee787; }}
    .dot-metric {{ background: #d2a8ff; }}
    .dot-column {{ background: #ffa657; }}
    .dot-event {{ background: #ff7b72; }}

    /* Type badge colours */
    .type-concept {{ background: rgba(88,166,255,0.2); color: #58a6ff; }}
    .type-dataset {{ background: rgba(126,231,135,0.2); color: #7ee787; }}
    .type-metric {{ background: rgba(210,168,255,0.2); color: #d2a8ff; }}
    .type-column {{ background: rgba(255,166,87,0.2); color: #ffa657; }}
    .type-event {{ background: rgba(255,123,114,0.2); color: #ff7b72; }}

    /* Edge type colours */
    .overlap-badge {{ background: #e3b34133; color: #e3b341; font-size: 9px; padding: 1px 5px; border-radius: 3px; margin-left: 4px; }}
  </style>
</head>
<body>

<div class="header">
  <h1>Opti on Opti - Entity & Concept Graph</h1>
  <span class="subtitle">All entities, concepts, topics, and semantic connections with descriptions</span>
  <span class="badge" id="badge-nodes"></span>
  <span class="badge" id="badge-edges"></span>
  <span class="badge" id="badge-topics"></span>
</div>

<div class="topic-tabs" id="topicTabs">
  <div class="topic-tab active" data-topic="all">All</div>
</div>

<div class="filter-bar">
  <span class="filter-label">Show:</span>
  <button class="filter-btn active" data-ntype="concept">Concepts <span class="cnt"></span></button>
  <button class="filter-btn active" data-ntype="dataset">Datasets <span class="cnt"></span></button>
  <button class="filter-btn active" data-ntype="metric">Metrics <span class="cnt"></span></button>
  <button class="filter-btn" data-ntype="column">Columns <span class="cnt"></span></button>
  <button class="filter-btn active" data-ntype="event">Events <span class="cnt"></span></button>
  <span class="filter-label" style="margin-left:12px">Scope:</span>
  <button class="scope-btn active" data-scope="connected">Connected</button>
  <button class="scope-btn" data-scope="standalone">Standalone</button>
  <div class="view-toggle">
    <button class="view-btn active" data-view="graph">Graph</button>
    <button class="view-btn" data-view="list">List</button>
  </div>
  <input class="search-box" id="searchBox" type="text" placeholder="Search entities...">
</div>

<div class="main">
  <div id="cy"></div>
  <div class="entity-list-view" id="listView"></div>
  <div class="sidebar">
    <div class="topic-detail" id="topicDetail">
      <h3 id="topicName"></h3>
      <div class="topic-desc" id="topicDesc"></div>
      <div class="topic-stat">Concepts: <span id="topicConcepts">-</span> | Datasets: <span id="topicDatasets">-</span> | Metrics: <span id="topicMetrics">-</span> | Events: <span id="topicEvents">-</span></div>
      <div class="topic-section">
        <div class="topic-section-title open" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">Concepts</div>
        <div class="topic-section-body open" id="topicConceptsList"></div>
      </div>
      <div class="topic-section">
        <div class="topic-section-title" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">Business Rules</div>
        <div class="topic-section-body" id="topicRulesList"></div>
      </div>
      <div class="topic-section">
        <div class="topic-section-title" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">Disambiguation</div>
        <div class="topic-section-body" id="topicDisambigList"></div>
      </div>
      <div class="topic-section">
        <div class="topic-section-title" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">Expansion Policy</div>
        <div class="topic-section-body" id="topicPolicyBody"></div>
      </div>
    </div>

    <div class="node-detail" id="nodeDetail">
      <div class="type-badge" id="nd-type"></div>
      <h3 id="nd-name"></h3>
      <div class="desc" id="nd-desc"></div>
      <div class="meta" id="nd-meta"></div>
      <div class="topic-tags" id="nd-topics"></div>
      <div class="edges-list" id="nd-edges"></div>
    </div>

    <h2 style="font-size:13px;font-weight:600;color:#f0f6fc;margin-bottom:6px">Spacing</h2>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
      <span style="font-size:11px;color:#8b949e">Dense</span>
      <input type="range" id="spacingSlider" min="1" max="10" value="5" style="flex:1;accent-color:#58a6ff;cursor:pointer">
      <span style="font-size:11px;color:#8b949e">Sparse</span>
    </div>

    <h2 style="font-size:13px;font-weight:600;color:#f0f6fc;margin-bottom:6px">Layout</h2>
    <div class="layout-btns">
      <button class="layout-btn active" data-layout="fcose">Force</button>
      <button class="layout-btn" data-layout="concentric">Concentric</button>
      <button class="layout-btn" data-layout="concepts-only">Concepts Only</button>
    </div>

    <div class="legend">
      <h2 style="font-size:13px;font-weight:600;color:#f0f6fc;margin-bottom:6px">Nodes</h2>
      <div class="legend-item"><div class="legend-dot" style="background:#58a6ff"></div> Concept</div>
      <div class="legend-item"><div class="legend-dot" style="background:#7ee787"></div> Dataset</div>
      <div class="legend-item"><div class="legend-dot" style="background:#d2a8ff"></div> Metric</div>
      <div class="legend-item"><div class="legend-dot" style="background:#ffa657"></div> Column</div>
      <div class="legend-item"><div class="legend-dot" style="background:#ff7b72"></div> Event</div>
      <h2 style="font-size:13px;font-weight:600;color:#f0f6fc;margin:10px 0 6px">Edges</h2>
      <div class="legend-item"><div class="legend-line" style="border-top:2px solid #8b949e"></div> composes</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px solid #58a6ff"></div> measured-by</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px solid #ffa657"></div> segmented-by</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px solid #7ee787"></div> derives-from</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px dashed #ff7b72"></div> distinct-from</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px dashed #e3b341"></div> informs</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px solid #d2a8ff"></div> filtered-by</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px solid #ff7b72"></div> tracked-in</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px dotted #e3b341"></div> correlates-with</div>
      <div class="legend-item"><div class="legend-line" style="border-top:2px solid #39d353"></div> belongs-to</div>
    </div>

    <div class="stats" id="statsPanel">
      <div class="stats-row"><span class="stats-label">Visible nodes</span><span class="stats-value" id="statNodes">0</span></div>
      <div class="stats-row"><span class="stats-label">Visible edges</span><span class="stats-value" id="statEdges">0</span></div>
      <div class="stats-row"><span class="stats-label">Topics</span><span class="stats-value" id="statTopics">0</span></div>
    </div>
  </div>
</div>

<script>
// === DATA ===
var GRAPH_DATA = {graph_json};
var TOPICS = {topics_json};

// Register fcose
if (typeof cytoscapeFcose !== 'undefined') cytoscape.use(cytoscapeFcose);

// === LOOKUPS ===
var nodesById = GRAPH_DATA.nodes;
var edges = GRAPH_DATA.edges;

var COLOURS = {{
  concept: '#58a6ff', dataset: '#7ee787', metric: '#d2a8ff',
  column: '#ffa657', event: '#ff7b72', unknown: '#8b949e'
}};

var EDGE_COLOURS = {{
  'composes': '#8b949e', 'measured-by': '#58a6ff', 'segmented-by': '#ffa657',
  'derives-from': '#7ee787', 'distinct-from': '#ff7b72', 'informs': '#e3b341',
  'filtered-by': '#d2a8ff', 'tracked-in': '#ff7b72', 'correlates-with': '#e3b341',
  'implemented-by': '#8b949e', 'scoped-by': '#8b949e', 'produces': '#d2a8ff',
  'belongs-to': '#39d353'
}};

// Connected node IDs
var connectedIds = new Set();
edges.forEach(function(e) {{ connectedIds.add(e.source); connectedIds.add(e.target); }});

// Edge index
var edgesByNode = {{}};
edges.forEach(function(e) {{
  if (!edgesByNode[e.source]) edgesByNode[e.source] = [];
  if (!edgesByNode[e.target]) edgesByNode[e.target] = [];
  edgesByNode[e.source].push(e);
  edgesByNode[e.target].push(e);
}});

// Short name helper
function shortName(name) {{
  if (!name) return '?';
  var parts = name.split('.');
  return parts[parts.length - 1];
}}

// === STATE ===
var activeTypes = new Set(['concept', 'dataset', 'metric', 'event']);
var showConnected = true;
var showStandalone = false;
var activeTopic = 'all';
var currentView = 'graph';
var cy;

// === HEADER BADGES ===
var typeCounts = {{}};
Object.values(nodesById).forEach(function(n) {{ typeCounts[n.type] = (typeCounts[n.type] || 0) + 1; }});
document.getElementById('badge-nodes').textContent = Object.values(nodesById).length + ' entities';
document.getElementById('badge-edges').textContent = edges.length + ' connections';
document.getElementById('badge-topics').textContent = Object.keys(TOPICS).length + ' topics';
document.getElementById('statTopics').textContent = Object.keys(TOPICS).length;

// Filter button counts
document.querySelectorAll('.filter-btn[data-ntype]').forEach(function(btn) {{
  var cnt = typeCounts[btn.dataset.ntype] || 0;
  btn.querySelector('.cnt').textContent = cnt;
}});

// === TOPIC TABS ===
(function() {{
  var tabs = document.getElementById('topicTabs');
  Object.keys(TOPICS).sort().forEach(function(slug) {{
    var t = TOPICS[slug];
    var tab = document.createElement('div');
    tab.className = 'topic-tab';
    tab.setAttribute('data-topic', slug);
    tab.innerHTML = t.name + '<span class="count">' + t.member_ids.length + '</span>';
    tabs.appendChild(tab);
  }});
}})();

// === BUILD CYTOSCAPE ELEMENTS ===
function buildElements() {{
  var elements = [];
  var visibleNodeIds = new Set();
  var search = document.getElementById('searchBox').value.toLowerCase().trim();

  Object.values(nodesById).forEach(function(n) {{
    if (!activeTypes.has(n.type)) return;
    if (search && n.name.toLowerCase().indexOf(search) < 0
        && (n.description || '').toLowerCase().indexOf(search) < 0) return;
    // Scope uses global connectivity (does this node have ANY edge
    // in the full graph?) so hiding a type doesn't reclassify nodes.
    var isConnected = connectedIds.has(n.id);
    if (isConnected && !showConnected) return;
    if (!isConnected && !showStandalone) return;

    visibleNodeIds.add(n.id);
    var label = shortName(n.name);
    var size = n.type === 'concept' ? 35 : n.type === 'column' ? 12 : 20;
    elements.push({{
      group: 'nodes',
      data: {{
        id: n.id, label: label, ntype: n.type,
        color: COLOURS[n.type] || COLOURS.unknown,
        size: size, desc: n.description || '',
        fullName: n.name,
        topics: n.topics || [],
        degree: (edgesByNode[n.id] || []).length,
      }}
    }});
  }});

  edges.forEach(function(e) {{
    if (visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)) {{
      elements.push({{
        group: 'edges',
        data: {{
          source: e.source, target: e.target,
          predicate: e.predicate || '',
          reasoning: e.reasoning || '',
          edgeColor: EDGE_COLOURS[e.predicate] || '#21262d',
        }}
      }});
    }}
  }});

  return elements;
}}

// === INIT GRAPH ===
function initGraph() {{
  var elements = buildElements();
  cy = cytoscape({{
    container: document.getElementById('cy'),
    elements: elements,
    style: [
      {{
        selector: 'node',
        style: {{
          'label': 'data(label)',
          'font-size': 8,
          'color': '#8b949e',
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'background-color': 'data(color)',
          'width': 'data(size)',
          'height': 'data(size)',
          'border-width': 0,
          'text-max-width': 80,
          'text-wrap': 'ellipsis',
        }}
      }},
      {{
        selector: 'node[ntype="concept"]',
        style: {{
          'shape': 'diamond',
          'font-size': 10,
          'font-weight': 600,
          'color': '#e1e4e8',
          'text-max-width': 120,
        }}
      }},
      {{
        selector: 'edge',
        style: {{
          'width': 1,
          'line-color': 'data(edgeColor)',
          'target-arrow-color': 'data(edgeColor)',
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.6,
          'curve-style': 'bezier',
          'opacity': 0.6,
        }}
      }},
      {{
        selector: 'edge[predicate="distinct-from"], edge[predicate="informs"], edge[predicate="correlates-with"]',
        style: {{ 'target-arrow-shape': 'none' }}
      }},
      {{
        selector: 'edge[predicate="distinct-from"]',
        style: {{ 'line-style': 'dashed' }}
      }},
      {{
        selector: 'edge[predicate="correlates-with"]',
        style: {{ 'line-style': 'dotted' }}
      }},
      {{
        selector: 'edge[predicate="informs"]',
        style: {{ 'line-style': 'dashed' }}
      }},
      {{ selector: '.highlighted', style: {{ 'opacity': 1, 'z-index': 20 }} }},
      {{ selector: '.faded', style: {{ 'opacity': 0.06 }} }},
      {{ selector: '.topic-member', style: {{ 'opacity': 1, 'z-index': 15 }} }},
      {{ selector: '.topic-member-concept', style: {{ 'border-width': 4, 'border-color': '#f778ba', 'opacity': 1, 'z-index': 20 }} }},
      {{ selector: '.selected-node', style: {{ 'border-width': 4, 'border-color': '#f0f6fc', 'opacity': 1, 'z-index': 30 }} }},
      {{ selector: '.hidden', style: {{ 'display': 'none' }} }},
      {{ selector: '.edge-highlighted', style: {{ 'opacity': 0.8, 'width': 2, 'z-index': 15 }} }},
    ],
    layout: {{ name: 'fcose', animate: false, quality: 'default', randomize: true,
              nodeRepulsion: 6000, idealEdgeLength: 80, edgeElasticity: 0.1,
              numIter: 1000, gravity: 0.3, nodeSeparation: 40 }},
    minZoom: 0.1, maxZoom: 5,
  }});

  cy.on('tap', 'node', function(evt) {{
    showNodeDetail(evt.target.id());
    if (activeTopic === 'all') highlightNeighbours(evt.target.id());
  }});

  cy.on('tap', function(evt) {{
    if (evt.target === cy) {{
      cy.elements().removeClass('highlighted selected-node faded topic-member topic-member-concept edge-highlighted');
      document.getElementById('nodeDetail').classList.remove('visible');
      if (activeTopic !== 'all') {{
        applyTopicLens(activeTopic);
      }}
    }}
  }});

  cy.on('mouseover', 'edge', function(evt) {{
    if (!evt.target.hasClass('faded')) {{
      evt.target.style('width', 2); evt.target.style('opacity', 0.9);
    }}
  }});
  cy.on('mouseout', 'edge', function(evt) {{
    if (!evt.target.hasClass('faded')) {{
      evt.target.removeStyle('width'); evt.target.removeStyle('opacity');
    }}
  }});

  updateStats();
}}

function refreshGraph() {{
  if (currentView !== 'graph') return;
  var elements = buildElements();
  cy.elements().remove();
  cy.add(elements);
  cy.layout({{ name: 'fcose', animate: false, quality: 'default', randomize: true,
              nodeRepulsion: 6000, idealEdgeLength: 80, numIter: 800,
              gravity: 0.3, nodeSeparation: 40 }}).run();
  // Re-apply topic lens if active
  if (activeTopic !== 'all') applyTopicLens(activeTopic);
  else updateStats();
}}

function highlightNeighbours(nodeId) {{
  cy.elements().addClass('faded');
  var node = cy.getElementById(nodeId);
  var neighbourhood = node.closedNeighborhood();
  neighbourhood.removeClass('faded').addClass('highlighted');
  node.addClass('selected-node');
}}

// === TOPIC SELECTION ===
function applyTopicLens(slug) {{
  var t = TOPICS[slug];
  var memberSet = new Set(t.member_ids);

  // Show topic detail
  var td = document.getElementById('topicDetail');
  td.classList.add('visible');
  document.getElementById('topicName').textContent = t.name;
  document.getElementById('topicDesc').textContent = t.description || '';

  // Count by type
  var counts = {{ concept: 0, dataset: 0, metric: 0, event: 0 }};
  t.member_ids.forEach(function(mid) {{
    var n = nodesById[mid];
    if (n && counts[n.type] !== undefined) counts[n.type]++;
  }});
  document.getElementById('topicConcepts').textContent = counts.concept;
  document.getElementById('topicDatasets').textContent = counts.dataset;
  document.getElementById('topicMetrics').textContent = counts.metric;
  document.getElementById('topicEvents').textContent = counts.event;

  // Concepts list
  var cl = document.getElementById('topicConceptsList');
  cl.innerHTML = '';
  (t.concepts || []).forEach(function(c) {{
    var div = document.createElement('div');
    div.className = 'topic-concept-item';
    div.innerHTML = '<div class="topic-concept-name">' + esc(c.label) + '</div>'
      + '<div class="topic-concept-desc">' + esc(c.description) + '</div>';
    cl.appendChild(div);
  }});

  // Business rules
  var rl = document.getElementById('topicRulesList');
  rl.innerHTML = '';
  (t.business_rules || []).forEach(function(r) {{
    var div = document.createElement('div');
    div.className = 'topic-rule';
    div.innerHTML = '<div class="topic-rule-term">' + esc(r.term) + '</div>'
      + '<div class="topic-rule-def">' + esc(r.definition) + '</div>';
    rl.appendChild(div);
  }});

  // Disambiguation
  var dl = document.getElementById('topicDisambigList');
  dl.innerHTML = '';
  (t.disambiguation || []).forEach(function(d) {{
    var div = document.createElement('div');
    div.className = 'topic-rule';
    div.innerHTML = '<div class="topic-rule-term">' + esc(d.term) + '</div>'
      + '<div class="topic-rule-def">' + esc(d.meaning) + '</div>';
    dl.appendChild(div);
  }});

  // Expansion policy
  var pb = document.getElementById('topicPolicyBody');
  pb.innerHTML = '';
  if (t.expansion_policy) {{
    var p = document.createElement('div');
    p.className = 'topic-policy-label';
    p.textContent = t.expansion_policy;
    pb.appendChild(p);
  }}

  // Highlight in graph
  if (currentView === 'graph') {{
    cy.elements().addClass('faded');
    cy.nodes().forEach(function(n) {{
      if (memberSet.has(n.id())) {{
        n.removeClass('faded hidden');
        if (n.data('ntype') === 'concept') n.addClass('topic-member-concept');
        else n.addClass('topic-member');
      }}
    }});
    cy.edges().forEach(function(e) {{
      if (memberSet.has(e.source().id()) && memberSet.has(e.target().id())) {{
        e.removeClass('faded').addClass('edge-highlighted');
      }}
    }});
    updateStats();
  }}
}}

document.getElementById('topicTabs').addEventListener('click', function(e) {{
  var tab = e.target.closest('.topic-tab');
  if (!tab) return;
  var slug = tab.getAttribute('data-topic');

  document.querySelectorAll('.topic-tab').forEach(function(t) {{ t.classList.remove('active'); }});
  tab.classList.add('active');
  activeTopic = slug;

  cy.elements().removeClass('highlighted faded selected-node topic-member topic-member-concept edge-highlighted hidden');
  document.getElementById('nodeDetail').classList.remove('visible');

  if (slug === 'all') {{
    document.getElementById('topicDetail').classList.remove('visible');
    if (currentView === 'graph') applyFilters();
    else renderListView();
    return;
  }}

  applyTopicLens(slug);
  if (currentView === 'list') renderListView();
}});

// === NODE DETAIL ===
function showNodeDetail(nodeId) {{
  var n = nodesById[nodeId];
  if (!n) return;

  var panel = document.getElementById('nodeDetail');
  panel.classList.add('visible');

  var typeBadge = document.getElementById('nd-type');
  typeBadge.textContent = n.type;
  typeBadge.className = 'type-badge type-' + n.type;

  document.getElementById('nd-name').textContent = n.name;
  document.getElementById('nd-desc').textContent = n.description || 'No description available.';

  var meta = [];
  if (n.confidence) meta.push('Confidence: ' + n.confidence);
  if (n.trust) meta.push('Trust: ' + n.trust);
  if (connectedIds.has(n.id)) meta.push('In concept graph');
  else meta.push('Standalone entity');
  meta.push((edgesByNode[n.id] || []).length + ' connections');
  document.getElementById('nd-meta').textContent = meta.join(' | ');

  // Topic tags
  var topicTags = document.getElementById('nd-topics');
  topicTags.innerHTML = '';
  (n.topics || []).forEach(function(slug) {{
    var tag = document.createElement('span');
    tag.className = 'topic-tag';
    tag.textContent = TOPICS[slug] ? TOPICS[slug].name : slug;
    tag.onclick = function() {{
      var tab = document.querySelector('.topic-tab[data-topic="' + slug + '"]');
      if (tab) tab.click();
    }};
    topicTags.appendChild(tag);
  }});

  // Edge list
  var nodeEdges = edgesByNode[nodeId] || [];
  var edgesDiv = document.getElementById('nd-edges');
  if (nodeEdges.length === 0) {{
    edgesDiv.innerHTML = '<div style="color:#484f58">No connections</div>';
  }} else {{
    edgesDiv.innerHTML = '<div style="color:#484f58;margin-bottom:4px;font-weight:600">' + nodeEdges.length + ' connections</div>';
    nodeEdges.forEach(function(e) {{
      var otherId = e.source === nodeId ? e.target : e.source;
      var other = nodesById[otherId];
      var otherName = other ? shortName(other.name) : otherId;
      var dir = e.source === nodeId ? '\\u2192' : '\\u2190';
      var colour = EDGE_COLOURS[e.predicate] || '#8b949e';
      var div = document.createElement('div');
      div.setAttribute('data-id', otherId);
      div.innerHTML = '<span class="edge-pred" style="color:' + colour + '">' + e.predicate + '</span> '
        + dir + ' <span style="color:' + (COLOURS[other ? other.type : ''] || '#8b949e') + '">' + esc(otherName) + '</span>';
      div.onclick = function() {{
        showNodeDetail(otherId);
        if (currentView === 'graph') {{
          var cyNode = cy.getElementById(otherId);
          if (cyNode.length) {{
            cy.animate({{ center: {{ eles: cyNode }}, zoom: 1.5 }}, {{ duration: 300 }});
            highlightNeighbours(otherId);
          }}
        }}
      }};
      edgesDiv.appendChild(div);
    }});
  }}
}}

// === FILTERS ===
document.querySelectorAll('.filter-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    var ntype = this.getAttribute('data-ntype');
    if (activeTypes.has(ntype)) {{ activeTypes.delete(ntype); this.classList.remove('active'); }}
    else {{ activeTypes.add(ntype); this.classList.add('active'); }}
    if (currentView === 'graph') {{
      // Must refreshGraph (not applyFilters) because buildElements
      // gates on activeTypes - nodes for disabled types are never
      // added to the Cytoscape instance.
      refreshGraph();
    }} else renderListView();
  }});
}});

document.querySelectorAll('.scope-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    var scope = this.getAttribute('data-scope');
    this.classList.toggle('active');
    if (scope === 'connected') showConnected = this.classList.contains('active');
    if (scope === 'standalone') showStandalone = this.classList.contains('active');
    if (currentView === 'graph') refreshGraph();
    else renderListView();
  }});
}});

function applyFilters() {{
  var search = document.getElementById('searchBox').value.toLowerCase().trim();
  cy.elements().removeClass('faded highlighted topic-member topic-member-concept edge-highlighted');
  cy.nodes().forEach(function(n) {{
    var show = activeTypes.has(n.data('ntype'));
    if (show) {{
      var isConn = connectedIds.has(n.id());
      if (isConn && !showConnected) show = false;
      if (!isConn && !showStandalone) show = false;
    }}
    if (show && search && n.data('label').toLowerCase().indexOf(search) < 0
        && (n.data('desc') || '').toLowerCase().indexOf(search) < 0) {{
      show = false;
    }}
    if (show) n.removeClass('hidden'); else n.addClass('hidden');
  }});
  cy.edges().forEach(function(e) {{
    if (!e.source().hasClass('hidden') && !e.target().hasClass('hidden')) e.removeClass('hidden');
    else e.addClass('hidden');
  }});
  updateStats();
}}

var searchTimeout;
document.getElementById('searchBox').addEventListener('input', function() {{
  clearTimeout(searchTimeout);
  var self = this;
  searchTimeout = setTimeout(function() {{
    if (activeTopic !== 'all') {{
      document.querySelector('.topic-tab[data-topic="all"]').click();
    }}
    if (currentView === 'graph') applyFilters();
    else renderListView();
  }}, 300);
}});

function updateStats() {{
  var vn = 0, ve = 0;
  cy.nodes().forEach(function(n) {{ if (!n.hasClass('hidden') && n.style('display') !== 'none' && !n.hasClass('faded')) vn++; }});
  cy.edges().forEach(function(e) {{ if (!e.hasClass('hidden') && e.style('display') !== 'none' && !e.hasClass('faded')) ve++; }});
  // In "all" mode without fading, count all visible
  if (activeTopic === 'all') {{
    vn = 0; ve = 0;
    cy.nodes().forEach(function(n) {{ if (!n.hasClass('hidden')) vn++; }});
    cy.edges().forEach(function(e) {{ if (!e.hasClass('hidden')) ve++; }});
  }}
  document.getElementById('statNodes').textContent = vn;
  document.getElementById('statEdges').textContent = ve;
}}

// === VIEW TOGGLE ===
document.querySelectorAll('.view-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    currentView = this.getAttribute('data-view');
    document.querySelectorAll('.view-btn').forEach(function(b) {{ b.classList.toggle('active', b.getAttribute('data-view') === currentView); }});
    document.getElementById('cy').style.display = currentView === 'graph' ? 'block' : 'none';
    document.getElementById('listView').style.display = currentView === 'list' ? 'block' : 'none';
    if (currentView === 'list') renderListView();
    else refreshGraph();
  }});
}});

// === LIST VIEW ===
function renderListView() {{
  var container = document.getElementById('listView');
  var groups = {{}};
  var search = document.getElementById('searchBox').value.toLowerCase().trim();
  var topicMembers = (activeTopic !== 'all') ? new Set(TOPICS[activeTopic].member_ids) : null;

  Object.values(nodesById).forEach(function(n) {{
    if (!activeTypes.has(n.type)) return;
    var isConn = connectedIds.has(n.id);
    if (isConn && !showConnected) return;
    if (!isConn && !showStandalone) return;
    if (topicMembers && !topicMembers.has(n.id)) return;
    if (search && n.name.toLowerCase().indexOf(search) < 0
        && (n.description || '').toLowerCase().indexOf(search) < 0) return;
    if (!groups[n.type]) groups[n.type] = [];
    groups[n.type].push(n);
  }});

  var order = ['concept', 'dataset', 'event', 'metric', 'column'];
  var html = '';
  var total = 0;
  order.forEach(function(type) {{
    var items = groups[type];
    if (!items || items.length === 0) return;
    items.sort(function(a, b) {{ return a.name.localeCompare(b.name); }});
    total += items.length;
    html += '<div style="margin-bottom:20px">';
    html += '<h3 style="font-size:14px;color:' + COLOURS[type] + ';margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px">'
      + type + 's (' + items.length + ')</h3>';
    items.forEach(function(n) {{
      var edgeCount = (edgesByNode[n.id] || []).length;
      var desc = n.description || '';
      var shortDesc = desc.length > 200 ? desc.substring(0, 200) + '...' : desc;
      html += '<div class="entity-item" onclick="showNodeDetail(\\'' + n.id + '\\')">';
      html += '<div class="name"><span class="type-dot dot-' + n.type + '"></span>' + esc(n.name) + '</div>';
      if (shortDesc) html += '<div class="short-desc">' + esc(shortDesc) + '</div>';
      if (edgeCount > 0) html += '<div style="font-size:10px;color:#484f58;margin-top:2px">' + edgeCount + ' connections</div>';
      html += '</div>';
    }});
    html += '</div>';
  }});

  container.innerHTML = html || '<div style="color:#484f58;padding:20px">No matching entities</div>';
  document.getElementById('statNodes').textContent = total;
  document.getElementById('statEdges').textContent = '-';
}}

// === LAYOUT TOGGLE ===
document.querySelectorAll('.layout-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    document.querySelectorAll('.layout-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    this.classList.add('active');
    var layoutName = this.getAttribute('data-layout');

    if (layoutName === 'concepts-only') {{
      cy.nodes().forEach(function(n) {{
        if (n.data('ntype') !== 'concept') n.addClass('hidden'); else n.removeClass('hidden');
      }});
      cy.edges().forEach(function(e) {{
        if (!e.source().hasClass('hidden') && !e.target().hasClass('hidden')) e.removeClass('hidden');
        else e.addClass('hidden');
      }});
      cy.layout({{ name: 'fcose', animate: true, animationDuration: 500,
        nodeRepulsion: 4000, idealEdgeLength: 60, gravity: 0.5, numIter: 500, fit: true }}).run();
      updateStats();
      return;
    }}

    applyFilters();
    var opts;
    if (layoutName === 'concentric') {{
      opts = {{ name: 'concentric', animate: true, animationDuration: 500,
        concentric: function(n) {{ return n.data('ntype') === 'concept' ? 100 - n.data('degree') : 0; }},
        levelWidth: function() {{ return 3; }}, fit: true }};
    }} else {{
      opts = {{ name: 'fcose', animate: true, animationDuration: 500,
        nodeRepulsion: 6000, idealEdgeLength: 80, numIter: 800,
        gravity: 0.3, nodeSeparation: 40, fit: true }};
    }}
    cy.layout(opts).run();
  }});
}});

// === HTML ESCAPE ===
function esc(s) {{
  if (!s) return '';
  var d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}}

// === SPACING SLIDER ===
var spacingTimeout;
document.getElementById('spacingSlider').addEventListener('input', function() {{
  clearTimeout(spacingTimeout);
  var self = this;
  spacingTimeout = setTimeout(function() {{
    if (currentView !== 'graph') return;
    var val = parseInt(self.value);
    // Scale: 1 = dense, 10 = very sparse
    var repulsion = 2000 + val * 4000;       // 6000 .. 42000
    var edgeLen = 30 + val * 40;             // 70 .. 430
    var separation = 10 + val * 20;          // 30 .. 210
    var gravity = 0.6 - val * 0.05;          // 0.55 .. 0.10
    cy.layout({{
      name: 'fcose', animate: true, animationDuration: 400,
      quality: 'default', randomize: false,
      nodeRepulsion: repulsion, idealEdgeLength: edgeLen,
      nodeSeparation: separation, gravity: gravity,
      numIter: 600, fit: true
    }}).run();
  }}, 200);
}});

// === INIT ===
initGraph();
</script>
</body>
</html>"""


def main():
    print("Loading graph data...")
    with open(GRAPH_PATH) as f:
        graph_data = json.load(f)

    print("Loading topics data...")
    with open(TOPICS_PATH) as f:
        topics_raw = json.load(f)

    print("Building compact topic data for embed...")
    topics_embed = build_topics_for_embed(topics_raw)

    graph_json = json.dumps(graph_data)
    topics_json = json.dumps(topics_embed)

    print(f"Graph JSON: {len(graph_json)} chars")
    print(f"Topics JSON: {len(topics_json)} chars")

    html = generate_html(graph_json, topics_json)
    with open(OUT_HTML, "w") as f:
        f.write(html)

    print(f"Wrote: {OUT_HTML} ({len(html)} chars)")


if __name__ == "__main__":
    main()
