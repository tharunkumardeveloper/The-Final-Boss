"""Every Cypher query Relay depends on. One graph per tenant: `mem:{tenant}`.

Parameters ending in `vec` are float lists, always wrapped in vecf32().
Vector `score` from db.idx.vector.queryNodes is a cosine DISTANCE: lower = closer.
"""
from functools import lru_cache

from . import config, registry as R

REL = R.REL_PATTERN  # every typed current-world fact edge (LIVES_IN|ON_PLAN|HAS_TICKET|...)

SCHEMA = [
    "CREATE INDEX FOR (e:Entity) ON (e.name_key)",
    "CREATE INDEX FOR (e:Entity) ON (e.type)",
    "CREATE INDEX FOR (f:Fact) ON (f.fact_id)",
    "CREATE INDEX FOR (f:Fact) ON (f.triple_key)",
    "CREATE INDEX FOR (f:Fact) ON (f.predicate)",
    "CREATE INDEX FOR (ep:Episode) ON (ep.episode_id)",
    "CREATE INDEX FOR (ep:Episode) ON (ep.customer)",
    "CREATE INDEX FOR (ep:Episode) ON (ep.session_id)",  # GRAPH.EXPLAIN showed every chat turn scanning all episodes
    "CREATE INDEX FOR (s:Session) ON (s.session_id)",
    "CREATE INDEX FOR (a:Agent) ON (a.agent_id)",
    "CREATE INDEX FOR (o:Order) ON (o.order_id)",
    "CREATE INDEX FOR (c:City) ON (c.location)",  # geospatial: nearest served city for a place we don't cover
    # fuzzy customer names for entity linking ("alise rao" finds Alice Rao); case- and typo-tolerant
    "CALL db.idx.fulltext.createNodeIndex('Customer', 'name')",
    f"CREATE VECTOR INDEX FOR (e:Entity) ON (e.embedding) OPTIONS {{dimension:{config.DIM}, similarityFunction:'cosine'}}",
    f"CREATE VECTOR INDEX FOR (ep:Episode) ON (ep.embedding) OPTIONS {{dimension:{config.DIM}, similarityFunction:'cosine'}}",
]

UPSERT_AGENT = "MERGE (a:Agent {agent_id:$id}) SET a.role=$role, a.trust=$trust, a.name=$id"

# Every node gets a readable `name`, so FalkorDB Browser captions show "alice rao LIVES_IN pune" instead of ids.
# Runs on every setup; only touches nodes that don't have one yet (older graphs).
BACKFILL_NAMES = [
    "MATCH (f:Fact) WHERE f.name IS NULL SET f.name = f.subject + ' ' + toUpper(f.predicate) + ' ' + f.object_value",
    "MATCH (ep:Episode) WHERE ep.name IS NULL SET ep.name = ep.speaker + ': ' + substring(ep.text, 0, 48)",
    "MATCH (s:Session) WHERE s.name IS NULL SET s.name = 'session ' + s.session_id",
    "MATCH (c:Community) WHERE c.name IS NULL SET c.name = 'cluster: ' + c.top[0]",
]

# ---------------------------------------------------------------- write path

# Episodic memory: one raw event (customer message, agent action, tool observation) with provenance.
WRITE_EPISODE = """
MERGE (a:Agent {agent_id:$agent})
MERGE (s:Session {session_id:$sid})
  ON CREATE SET s.started_at=$at, s.started_dt=localdatetime($at_dt), s.customer=$customer, s.name='session ' + $sid
SET s.ended_dt = CASE WHEN s.ended_at IS NULL OR s.ended_at < $at THEN localdatetime($at_dt) ELSE s.ended_dt END
SET s.ended_at = CASE WHEN s.ended_at IS NULL OR s.ended_at < $at THEN $at ELSE s.ended_at END
CREATE (a)-[:WROTE]->(ep:Episode {episode_id:$eid, name:$speaker + ': ' + substring($text, 0, 48), text:$text,
                                  speaker:intern($speaker), embedding:vecf32($vec), at:localdatetime($at_dt),
                                  recorded_at:$at, session_id:$sid, source_agent:intern($agent), customer:$customer,
                                  extraction_model:$xmodel, extraction_prompt:$xprompt})-[:IN]->(s)
WITH ep
FOREACH (_ IN CASE WHEN $speaker = 'customer' THEN [1] ELSE [] END | SET ep:CustomerMessage)
FOREACH (_ IN CASE WHEN $speaker = 'agent' THEN [1] ELSE [] END | SET ep:AgentReply)
FOREACH (_ IN CASE WHEN $speaker = 'action' THEN [1] ELSE [] END | SET ep:InternalNote)
FOREACH (_ IN CASE WHEN $speaker = 'noc' THEN [1] ELSE [] END | SET ep:NocAlert)
FOREACH (_ IN CASE WHEN $speaker STARTS WITH 'tool:' OR $speaker STARTS WITH 'mcp:' THEN [1] ELSE [] END | SET ep:ToolResult)
WITH ep
UNWIND $mentions AS m
MERGE (e:Entity {name_key:m.key})
  ON CREATE SET e.name=m.name, e.type=m.type, e.embedding=vecf32(m.vec), e.created_at=$at
FOREACH (_ IN CASE WHEN m.type = 'customer' THEN [1] ELSE [] END | SET e:Customer)
FOREACH (_ IN CASE WHEN m.type = 'ticket' THEN [1] ELSE [] END | SET e:Ticket)
MERGE (ep)-[:MENTIONS]->(e)
"""

# Semantic memory + contradiction handling in ONE statement (writes to one graph are serialized, so this
# is atomic: no reader ever sees two current values, and concurrent writers cannot duplicate anything).
# - The triple key makes a repeated fact a corroboration (new DERIVED edge), never a duplicate.
# - A single-valued fact retires older active facts for the same subject+predicate. Never itself, never on an
#   unchanged value, and with policy "trust" only the same agent's claims: cross-agent disagreements are kept.
# - World clock: old.valid_to = when the new fact became true. System clock: old.expired_at = now.
# - Current facts are also a typed edge between the entities ((:Customer)-[:LIVES_IN {fact_id}]->(:City)); a retired
#   fact's edge is deleted, so traversals and algorithms see only the current world while Fact nodes keep history.
# Labels and the edge type can't be query parameters in Cypher, so the statement is built per predicate from the
# registry (validated names only, never user text).
@lru_cache
def write_fact(predicate):
    s_label, o_label = R.label(R.subject_type(predicate)), R.label(R.object_type(predicate))
    return WRITE_FACT.replace("{S_LABEL}", s_label).replace("{O_LABEL}", o_label).replace("{REL}", R.rel_type(predicate))


WRITE_FACT = """
MATCH (ep:Episode {episode_id:$eid})
MERGE (ag:Agent {agent_id:$agent})
MERGE (s:Entity {name_key:$s})
  ON CREATE SET s.name=$s_name, s.type=$s_type, s.embedding=vecf32($s_vec), s.created_at=$at
SET s:{S_LABEL}
MERGE (o:Entity {name_key:$o})
  ON CREATE SET o.name=$o_name, o.type=$o_type, o.embedding=vecf32($o_vec), o.created_at=$at
SET o:{O_LABEL}
MERGE (ep)-[:MENTIONS]->(s)
MERGE (ep)-[:MENTIONS]->(o)
MERGE (f:Fact {triple_key:$tk, active:true})
  ON CREATE SET f.fact_id=$fid, f.predicate=intern($p), f.subject=$s, f.object_value=$o, f.name=$s + ' {REL} ' + $o,
                f.valid_from=$vf, f.recorded_at=$at, f.asserted_by=intern($agent), f.is_new=true,
                f.valid_from_dt=localdatetime($vf_dt), f.learned_dt=localdatetime($at_dt),
                f.cardinality=$card, f.policy=$policy, f.registry=$registry, f.corroboration_count=1
  ON MATCH  SET f.is_new=false, f.corroboration_count=coalesce(f.corroboration_count, 1) + 1
SET f:Current
CREATE (ep)-[:DERIVED]->(f)
MERGE (f)-[:WRITTEN_BY]->(ag)
SET ag.last_active = $at, ag.last_active_dt = localdatetime($at_dt),
    ag.facts_written = coalesce(ag.facts_written, 0) + CASE WHEN f.is_new THEN 1 ELSE 0 END
FOREACH (_ IN CASE WHEN f.is_new THEN [1] ELSE [] END |
  CREATE (f)-[:ABOUT {role:'subject'}]->(s), (f)-[:ABOUT {role:'object'}]->(o),
         (s)-[:{REL} {predicate:$p, fact_id:$fid, valid_from:f.valid_from}]->(o))
WITH f, s
OPTIONAL MATCH (old:Fact {predicate:$p, active:true})-[:ABOUT {role:'subject'}]->(s)
WHERE $single AND old.fact_id <> f.fact_id AND old.object_value <> $o
  AND ($any_agent OR old.asserted_by = $agent)
WITH f, s, collect(old) AS olds
FOREACH (old IN olds |
  SET old.active=false, old.valid_to=f.valid_from, old.expired_at=$at, old.superseded_by=f.fact_id,
      old.valid_to_dt=localdatetime($vf_dt), old.expired_dt=localdatetime($at_dt)
  REMOVE old:Current SET old:Superseded
  CREATE (f)-[:SUPERSEDES]->(old))
WITH f, s, olds, [x IN olds | x.fact_id] AS old_ids, [x IN olds | x.object_value] AS old_objs
OPTIONAL MATCH (s)-[r]->(was:Entity) WHERE r.fact_id IN old_ids AND type(r) <> 'WAS'
FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
  CREATE (s)-[:WAS {predicate:r.predicate, fact_id:r.fact_id, ended_by:f.fact_id, valid_to:f.valid_from, ended_at:$at,
                    valid_from:coalesce(r.valid_from, head([x IN olds WHERE x.fact_id = r.fact_id | x.valid_from]))}]->(was))
DELETE r
WITH DISTINCT f, f.is_new AS is_new, old_ids, old_objs
REMOVE f.is_new
RETURN f.fact_id, is_new, old_ids, old_objs, f.valid_from
"""

# A fact that stopped being true with no replacement ("I no longer live in Chennai"). Both clocks close,
# history stays, the episode that said so is linked by RETIRED, and the current-world RELATED edge goes.
# $o = '' retires whatever value is current. Same agent-scoping as SUPERSEDE.
RETIRE = """
MATCH (ep:Episode {episode_id:$eid})
MATCH (f:Fact {predicate:$p, active:true})-[:ABOUT {role:'subject'}]->(s:Entity {name_key:$s})
WHERE ($o = '' OR f.object_value = $o) AND ($any_agent OR f.asserted_by = $agent)
SET f.active=false, f.valid_to=$vt, f.expired_at=$at, f.retired_by=$eid,
    f.valid_to_dt=localdatetime($vt_dt), f.expired_dt=localdatetime($at_dt)
REMOVE f:Current SET f:Retired
CREATE (ep)-[:RETIRED]->(f)
WITH s, f
OPTIONAL MATCH (s)-[r {fact_id:f.fact_id}]->(was:Entity) WHERE type(r) <> 'WAS'
FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
  CREATE (s)-[:WAS {predicate:r.predicate, fact_id:r.fact_id, valid_to:$vt, ended_at:$at,
                    valid_from:coalesce(r.valid_from, f.valid_from)}]->(was))
DELETE r
RETURN DISTINCT f.fact_id, f.object_value
"""

# Everything said with one customer, grouped into sessions by the caller.
# Each message with the facts its episode DERIVED: episodic memory, and the semantic/procedural memory it produced.
CONVERSATION = """
MATCH (ep:Episode {customer:$c})-[:IN]->(s:Session)
OPTIONAL MATCH (ep)-[:DERIVED]->(f:Fact)
WITH s, ep, collect(CASE WHEN f IS NULL THEN NULL ELSE [f.fact_id, f.predicate, f.object_value, f.active] END) AS derived
RETURN s.session_id, s.started_at, s.summary, ep.episode_id, ep.speaker, ep.source_agent, ep.text, ep.recorded_at, derived
ORDER BY ep.recorded_at, id(ep)
LIMIT $limit
"""

ENTITY_EXISTS = "MATCH (e:Entity {name_key:$k}) RETURN e.type LIMIT 1"
TOPIC_WORDS = """
MATCH (e:Entity) WHERE e.type IN ['issue', 'fix', 'playbook', 'guide', 'faq', 'service', 'outage', 'reason', 'topic']
RETURN e.name_key
"""
OBJECTS_OF = "MATCH (:Fact {predicate:$p})-[:ABOUT {role:'object'}]->(o:Entity) RETURN DISTINCT o.name_key"
ADD_ALIAS = """
MATCH (e:Entity {name_key:$k})
SET e.aliases = CASE WHEN $a IN coalesce(e.aliases, []) THEN e.aliases ELSE coalesce(e.aliases, []) + [$a] END
"""

ALIAS_CANDIDATES = """
CALL db.idx.vector.queryNodes('Entity', 'embedding', 5, vecf32($vec)) YIELD node, score
WHERE node.type = $type
RETURN node.name_key, score ORDER BY score ASC LIMIT 1
"""

# ---------------------------------------------------------------- read path

# Constraints shown in FalkorDB Browser's schema view. (kind, label, property); unique ones need the range index above.
CONSTRAINTS = [
    ("UNIQUE", "Entity", "name_key"),   # one canonical node per thing: memory compounds instead of duplicating
    ("UNIQUE", "Fact", "fact_id"),
    ("UNIQUE", "Session", "session_id"),
    ("UNIQUE", "Order", "order_id"),
    # MANDATORY is checked when MERGE creates the node, before ON CREATE SET runs: only properties in the MERGE
    # pattern itself (or in a CREATE) can be mandatory. A Fact is merged on triple_key; fact_id comes after.
    ("MANDATORY", "Fact", "triple_key"),
    ("MANDATORY", "Episode", "episode_id"),
]
# Customers named with a typo, through the full-text index ('%alise%' = one edit away). Best score first; the
# edit-distance tie-break between equal scores is computed in Python (retrieve._fuzzy_pick).
FUZZY_CUSTOMERS = """
CALL db.idx.fulltext.queryNodes('Customer', $q) YIELD node, score
RETURN node.name_key, score ORDER BY score DESC LIMIT 20
"""

# Read path, round trip 1 of 2: every way into the graph for one question, as one UNION of index lookups.
#  exact:  each word n-gram of the question looked up on the Entity.name_key range index (no scan of every name);
#          all types come back, recall seeds from customers/tickets/cities/outages/plans/routers only
#  name:   customers sharing a word with the question (full-text, exact words): unique first names
#  fuzzy:  customers one edit from a longer word (full-text '%w%'): typos
#  vector: episodes similar to the question -> the entities they mention (score is a distance: ascending; one
#          episode gives its entities equal scores, so name breaks the tie and recall is deterministic)
# A graph without the 'Customer' full-text index just returns no name/fuzzy rows.
RECALL_LINK = """
MATCH (e:Entity) WHERE e.name_key IN $grams
RETURN 'exact' AS src, e.name_key AS key, e.type AS type, 0.0 AS score
UNION ALL
CALL db.idx.fulltext.queryNodes('Customer', $names) YIELD node, score
RETURN 'name' AS src, node.name_key AS key, 'customer' AS type, score ORDER BY score DESC LIMIT 50
UNION ALL
CALL db.idx.fulltext.queryNodes('Customer', $fuzzy) YIELD node, score
RETURN 'fuzzy' AS src, node.name_key AS key, 'customer' AS type, score ORDER BY score DESC LIMIT 20
UNION ALL
CALL db.idx.vector.queryNodes('Episode', 'embedding', $k, vecf32($qvec)) YIELD node AS ep, score
MATCH (ep)-[:MENTIONS]->(e:Entity)
RETURN 'vector' AS src, e.name_key AS key, e.type AS type, min(score) AS score ORDER BY score ASC, key ASC LIMIT $limit
"""

# Associative recall: expand from seed entities over current-world RELATED edges, then collect
# every fact (current and superseded) about the reached entities, with support = best agent trust and
# salience = the higher PageRank salience of the fact's entities (null before consolidation has run).
_EXPAND = {
    0: "WITH collect(DISTINCT seed) AS ns",
    1: f"OPTIONAL MATCH (seed)-[:{REL}]-(n:Entity)\nWITH collect(DISTINCT seed) + collect(DISTINCT n) AS ns",
}


def retrieve_facts(hops):
    if hops in _EXPAND:
        expand = f"""{_EXPAND[hops]}
UNWIND ns AS n
WITH DISTINCT n LIMIT $max_entities
MATCH (f:Fact)-[:ABOUT]->(n)
WITH DISTINCT f LIMIT $max_facts"""
    else:  # the caps cut the farthest entities and facts first: a hub one hop out must not crowd out a 2-hop path
        expand = f"""OPTIONAL MATCH p = (seed)-[:{REL}*1..{int(hops)}]-(n:Entity)
WITH collect({{n: seed, d: 0}}) + collect({{n: n, d: length(p)}}) AS ns
UNWIND ns AS x
WITH x.n AS n, min(x.d) AS d WHERE n IS NOT NULL
WITH n, d ORDER BY d LIMIT $max_entities
MATCH (f:Fact)-[:ABOUT]->(n)
WITH f, min(d) AS d ORDER BY d LIMIT $max_facts"""
    return f"""
MATCH (seed:Entity) WHERE seed.name_key IN $seeds
{expand}
MATCH (f)<-[:DERIVED]-(ep:Episode)<-[:WROTE]-(a:Agent)
WITH f, max(a.trust) AS support, max(ep.recorded_at) AS last_seen, collect(DISTINCT a.agent_id) AS agents
OPTIONAL MATCH (f)-[:ABOUT]->(x:Entity)
WITH f, support, last_seen, agents, max(x.salience) AS salience
RETURN f.fact_id, f.subject, f.predicate, f.object_value, f.active, f.valid_from, f.valid_to,
       f.recorded_at, f.expired_at, f.asserted_by, support, last_seen, agents, salience
"""


# Read-time conflict resolution: active claims for one subject+predicate, best supported first.
ACTIVE_CLAIMS = """
MATCH (f:Fact {predicate:$p, active:true})-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s})
MATCH (f)<-[:DERIVED]-(ep:Episode)<-[:WROTE]-(a:Agent)
WITH f, max(a.trust) AS support, max(ep.recorded_at) AS last_seen
RETURN f.fact_id, f.object_value, f.asserted_by, support, last_seen
ORDER BY support DESC, last_seen DESC
"""

# Two clocks. World: what was TRUE at $t. Belief: what the system HAD ON FILE at $t.
WORLD_AT = """
MATCH (f:Fact)-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s})
WHERE f.valid_from <= $t AND (f.valid_to IS NULL OR f.valid_to > $t)
  AND f.recorded_at <= $now
RETURN f.predicate, f.object_value, f.fact_id ORDER BY f.predicate
"""

BELIEF_AT = """
MATCH (f:Fact)-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s})
WHERE f.recorded_at <= $t AND (f.expired_at IS NULL OR f.expired_at > $t)
RETURN f.predicate, f.object_value, f.fact_id ORDER BY f.predicate
"""

FACT_HISTORY = """
MATCH (f:Fact)-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s})
OPTIONAL MATCH (f)<-[:DERIVED]-(ep:Episode)
WITH f, collect(DISTINCT ep.source_agent) AS agents
RETURN f.fact_id, f.predicate, f.object_value, f.active, f.valid_from, f.valid_to,
       f.recorded_at, f.expired_at, f.asserted_by, agents
ORDER BY f.predicate, f.recorded_at
"""

# The path behind an answer: fact -> subject/object -> source episode -> session -> agent,
# plus whatever the fact replaced.
EXPLAIN = """
MATCH (f:Fact) WHERE f.fact_id IN $fids
MATCH (f)-[:ABOUT {role:'subject'}]->(s:Entity)
MATCH (f)-[:ABOUT {role:'object'}]->(o:Entity)
MATCH (f)<-[:DERIVED]-(ep:Episode)-[:IN]->(ses:Session)
MATCH (ep)<-[:WROTE]-(a:Agent)
OPTIONAL MATCH (f)-[:SUPERSEDES]->(old:Fact)
RETURN f.fact_id, f.predicate, f.object_value, f.active, s.name_key, s.type, o.name_key, o.type,
       ep.episode_id, ep.text, ep.speaker, ep.recorded_at, ses.session_id, a.agent_id,
       old.fact_id, old.object_value
"""

NEIGHBORHOOD = f"""
MATCH (c:Entity {{name_key:$k}})
OPTIONAL MATCH (c)-[:{REL}*1..2]-(n:Entity)
WITH c, collect(DISTINCT n) AS ns
UNWIND [c] + ns AS e
MATCH (f:Fact)-[:ABOUT {{role:'subject'}}]->(e)
MATCH (f)-[:ABOUT {{role:'object'}}]->(o:Entity)
RETURN DISTINCT f.fact_id, f.predicate, f.active, e.name_key, e.type, o.name_key, o.type
"""

# ---------------------------------------------------------------- knowledge sharing
# An agent used these facts (to reply, answer or act). One CONSULTED edge per agent+fact, counting uses.
CONSULT = """
MATCH (a:Agent {agent_id:$agent})
UNWIND $fids AS fid
MATCH (f:Fact {fact_id:fid})
MERGE (a)-[c:CONSULTED]->(f)
  ON CREATE SET c.count = 0, c.first = $at
SET c.count = c.count + 1, c.last = $at
RETURN f.asserted_by, count(*)
"""

SHARING_AGENTS = """
MATCH (a:Agent)
OPTIONAL MATCH (w:Fact {asserted_by:a.agent_id})
WITH a, count(w) AS wrote
OPTIONAL MATCH (a)-[c:CONSULTED]->(f:Fact)
RETURN a.agent_id, wrote, count(f) AS consulted,
       count(CASE WHEN f.asserted_by <> a.agent_id THEN 1 END) AS from_others, sum(c.count) AS uses
ORDER BY a.agent_id
"""

SHARING_FLOWS = """
MATCH (a:Agent)-[:CONSULTED]->(f:Fact) WHERE f.asserted_by <> a.agent_id
RETURN f.asserted_by, a.agent_id, count(f) ORDER BY count(f) DESC
"""

SHARING_TOP = """
MATCH (a:Agent)-[c:CONSULTED]->(f:Fact)
WITH f, collect(DISTINCT a.agent_id) AS readers, sum(c.count) AS uses
WHERE any(r IN readers WHERE r <> f.asserted_by)
RETURN f.fact_id, f.subject, f.predicate, f.object_value, f.asserted_by, readers, uses
ORDER BY uses DESC LIMIT $n
"""

# ---------------------------------------------------------------- coordination

HANDOFF = """
MATCH (a:Agent {agent_id:$from_agent}), (t:Entity {name_key:$ticket})
CREATE (a)-[:HANDED_OFF {handoff_id:randomUUID(), at:$at, to:$to_agent, note:$note}]->(t)
"""

PICKUP = """
MATCH (a:Agent {agent_id:$agent}), (t:Entity {name_key:$ticket})
CREATE (a)-[:PICKED_UP {at:$at}]->(t)
"""

TICKETS = """
MATCH (t:Entity {type:'ticket'})
OPTIONAL MATCH (st:Fact {predicate:'has_status', active:true})-[:ABOUT {role:'subject'}]->(t)
OPTIONAL MATCH (asg:Fact {predicate:'assigned_to', active:true})-[:ABOUT {role:'subject'}]->(t)
OPTIONAL MATCH (c:Entity)-[:HAS_TICKET]->(t)
OPTIONAL MATCH (t)-[:TICKET_ABOUT]->(i:Entity)
RETURN t.name_key, st.object_value, asg.object_value, c.name_key, collect(DISTINCT i.name_key)
ORDER BY t.name_key
"""

HANDOFF_TRAIL = """
MATCH (a:Agent)-[r:HANDED_OFF|PICKED_UP]->(:Entity {name_key:$ticket})
RETURN a.agent_id, type(r), r.at, r.to, r.note ORDER BY r.at
"""

# Procedural memory: fixes that resolved an issue before.
FIXES_FOR = """
MATCH (fx:Entity)<-[:ABOUT {role:'subject'}]-(f:Fact {predicate:'resolves', active:true})-[:ABOUT {role:'object'}]->(i:Entity {name_key:$issue})
MATCH (f)<-[:DERIVED]-(ep:Episode)
RETURN fx.name_key, count(DISTINCT ep) AS times ORDER BY times DESC
"""

# Procedural memory, fuzzy: fixes that resolved a *similar* issue (vector neighbours of this issue entity).
FIXES_FOR_SIMILAR = """
MATCH (i:Entity {name_key:$issue})
CALL db.idx.vector.queryNodes('Entity', 'embedding', 10, i.embedding) YIELD node AS sim, score
WITH sim, score WHERE sim.type = 'issue' AND score < $max_dist
MATCH (fx:Entity)<-[:ABOUT {role:'subject'}]-(f:Fact {predicate:'resolves', active:true})-[:ABOUT {role:'object'}]->(sim)
MATCH (f)<-[:DERIVED]-(ep:Episode)
RETURN fx.name_key, sim.name_key, min(score) AS dist, count(DISTINCT ep) AS times
ORDER BY dist ASC, times DESC
"""

# ---------------------------------------------------------------- consolidation (graph algorithms)

# labelPropagation rejects relationship types that don't exist in the graph yet, so the caller passes only the
# fact-edge types present (from db.relationshipTypes()).
def communities(rel_types):
    types = ", ".join(f"'{t}'" for t in rel_types if t in R.REL_TYPES)
    return f"""
CALL algo.labelPropagation({{nodeLabels:['Entity'], relationshipTypes:[{types}], maxIterations:10}})
YIELD node, communityId
SET node.community = communityId
"""


REL_TYPES_PRESENT = "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"

# PageRank over Entity nodes only: with the label set, only Entity-to-Entity edges count, i.e. the fact edges.
SALIENCE = """
CALL algo.pageRank('Entity', null) YIELD node, score
SET node.salience = score
"""

BUILD_COMMUNITY_NODES = """
MATCH (old:Community) DETACH DELETE old
WITH count(*) AS _
MATCH (e:Entity) WHERE e.community IS NOT NULL
WITH e ORDER BY e.salience DESC
WITH e.community AS cid, collect(e) AS members
WHERE size(members) > 1
CREATE (c:Community {community_id:cid, size:size(members), name:'cluster: ' + members[0].name_key,
                     top:[m IN members[0..4] | m.name_key], salience:members[0].salience})
WITH c, members
UNWIND members AS m
CREATE (m)-[:IN_COMMUNITY]->(c)
RETURN count(DISTINCT c)
"""

TOP_COMMUNITIES = """
MATCH (c:Community) RETURN c.community_id, c.size, c.top, c.salience, c.summary ORDER BY c.salience DESC LIMIT $n
"""

COMMUNITY_FACTS = """
MATCH (c:Community {community_id:$cid})<-[:IN_COMMUNITY]-(e:Entity)-[r]->(o:Entity)-[:IN_COMMUNITY]->(c)
WHERE r.fact_id IS NOT NULL
RETURN e.name_key, r.predicate, o.name_key LIMIT 40
"""

SET_COMMUNITY_SUMMARY = "MATCH (c:Community {community_id:$cid}) SET c.summary = $summary"

# ---------------------------------------------------------------- conversation

SESSION_EPISODES = """
MATCH (ep:Episode {session_id:$sid})
RETURN ep.speaker, ep.text, ep.recorded_at, ep.customer ORDER BY ep.recorded_at, id(ep)
"""

SET_SESSION_SUMMARY = "MATCH (s:Session {session_id:$sid}) SET s.summary = $summary"

# ---------------------------------------------------------------- API / UI reads

STATS = """
OPTIONAL MATCH (f:Fact)
WITH count(CASE WHEN f.active = true THEN 1 END) AS cur, count(CASE WHEN f.active = false THEN 1 END) AS old
OPTIONAL MATCH (ep:Episode) WITH cur, old, count(ep) AS eps
OPTIONAL MATCH (e:Entity) WITH cur, old, eps, count(e) AS ents, count(CASE WHEN e.type = 'customer' THEN 1 END) AS custs
RETURN cur, old, eps, ents, custs
"""

CONFLICT_COUNT = """
MATCH (f:Fact {active:true})-[:ABOUT {role:'subject'}]->(s:Entity)
WHERE f.predicate IN $preds
WITH s.name_key AS s, f.predicate AS p, count(DISTINCT f.object_value) AS n
WHERE n > 1 RETURN count(*)
"""

CUSTOMERS = """
MATCH (c:Entity {type:'customer'})
OPTIONAL MATCH (f:Fact {active:true})-[:ABOUT {role:'subject'}]->(c)
WITH c, collect([f.predicate, f.object_value, f.recorded_at, f.asserted_by]) AS facts
OPTIONAL MATCH (ep:Episode)-[:MENTIONS]->(c)
RETURN c.name_key, facts, max(ep.recorded_at) ORDER BY c.name_key
"""

# Entity nodes + fact edges (current and superseded) for the live graph.
GRAPH_ALL = """
MATCH (f:Fact)-[:ABOUT {role:'subject'}]->(s:Entity), (f)-[:ABOUT {role:'object'}]->(o:Entity)
RETURN f.fact_id, f.predicate, f.active, s.name_key, s.type, s.salience, s.community,
       o.name_key, o.type, o.salience, o.community, f.recorded_at, f.expired_at
ORDER BY f.active DESC, f.recorded_at DESC LIMIT $limit
"""


def graph_focus(depth):
    return f"""
MATCH (c:Entity {{name_key:$k}})
OPTIONAL MATCH (c)-[:{REL}*1..{int(depth)}]-(n:Entity)
WITH collect(DISTINCT c) + collect(DISTINCT n) AS ns
UNWIND ns AS e
MATCH (f:Fact)-[:ABOUT]->(e)
WITH DISTINCT f LIMIT $limit
MATCH (f)-[:ABOUT {{role:'subject'}}]->(s:Entity), (f)-[:ABOUT {{role:'object'}}]->(o:Entity)
RETURN f.fact_id, f.predicate, f.active, s.name_key, s.type, s.salience, s.community,
       o.name_key, o.type, o.salience, o.community, f.recorded_at, f.expired_at
"""


CARD_FACT = """
MATCH (f:Fact {fact_id:$id})-[:ABOUT {role:'subject'}]->(s:Entity)
MATCH (f)-[:ABOUT {role:'object'}]->(o:Entity)
OPTIONAL MATCH (f)<-[:DERIVED]-(ep:Episode)
OPTIONAL MATCH (f)-[:SUPERSEDES]->(old:Fact)
OPTIONAL MATCH (newer:Fact)-[:SUPERSEDES]->(f)
WITH f, s, o, ep, collect(DISTINCT old.object_value) AS replaced, collect(DISTINCT newer.object_value) AS replaced_by
ORDER BY ep.recorded_at
RETURN f.predicate, f.active, f.valid_from, f.valid_to, f.recorded_at, f.expired_at, f.asserted_by,
       s.name_key, s.type, o.name_key, o.type, replaced, replaced_by,
       collect([ep.episode_id, ep.speaker, ep.text, ep.recorded_at, ep.session_id, ep.source_agent])
"""

CARD_EPISODE = """
MATCH (ep:Episode {episode_id:$id})
OPTIONAL MATCH (ep)-[:DERIVED]->(f:Fact)
RETURN ep.speaker, ep.text, ep.recorded_at, ep.session_id, ep.source_agent, ep.customer,
       collect([f.fact_id, f.subject, f.predicate, f.object_value, f.active])
"""

CARD_ENTITY = """
MATCH (e:Entity {name_key:$id})
OPTIONAL MATCH (f:Fact)-[r:ABOUT]->(e)
WITH e, collect([f.fact_id, f.predicate, f.object_value, f.active, f.valid_from, f.valid_to, f.recorded_at,
                 r.role, f.subject]) AS facts
OPTIONAL MATCH (ep:Episode)-[:MENTIONS]->(e)
RETURN e.type, e.salience, e.community, facts, collect(DISTINCT ep.session_id), count(DISTINCT ep)
"""

CARD_SESSION = """
MATCH (s:Session {session_id:$id})
OPTIONAL MATCH (ep:Episode)-[:IN]->(s)
RETURN s.customer, s.started_at, s.summary, count(ep), collect(DISTINCT ep.source_agent)
"""

CARD_AGENT = """
MATCH (a:Agent {agent_id:$id})
OPTIONAL MATCH (a)-[:WROTE]->(ep:Episode)
OPTIONAL MATCH (a)-[h:HANDED_OFF|PICKED_UP]->()
RETURN a.role, a.trust, count(DISTINCT ep), count(DISTINCT h)
"""

CARD_COMMUNITY = """
MATCH (c:Community {community_id:$id})
OPTIONAL MATCH (e:Entity)-[:IN_COMMUNITY]->(c)
RETURN c.size, c.top, c.salience, c.summary, collect(e.name_key)
"""

TICKET_OPENED = """
MATCH (f:Fact {predicate:'has_ticket'})-[:ABOUT {role:'object'}]->(t:Entity {type:'ticket'})
RETURN t.name_key, min(f.recorded_at)
"""

# The ticket as one readable node (intake spec section 7): everything intake learned, for the resolver and Browser.
TICKET_PROFILE = """
MATCH (t:Entity {name_key:$t})
OPTIONAL MATCH (f:Fact {active:true})-[:ABOUT {role:'subject'}]->(t)
WITH t, collect(f) AS fs
SET t:Ticket, t.name = toUpper($t),
    t.opened_at = coalesce(t.opened_at, reduce(m = null, f IN fs | CASE WHEN m IS NULL OR f.recorded_at < m
                                                                       THEN f.recorded_at ELSE m END)),
    t.closed_at = head([f IN fs WHERE f.predicate = 'has_status' AND f.object_value = 'resolved' | f.valid_from]),
    t.closed_dt = head([f IN fs WHERE f.predicate = 'has_status' AND f.object_value = 'resolved' | f.valid_from_dt]),
    t.status = head([f IN fs WHERE f.predicate = 'has_status' | f.object_value]),
    t.priority = coalesce(head([f IN fs WHERE f.predicate = 'has_priority' | f.object_value]), 'normal'),
    t.issue_type = head([f IN fs WHERE f.predicate = 'issue_type' | f.object_value]),
    t.issues = [f IN fs WHERE f.predicate = 'ticket_about' | f.object_value],
    t.started = head([f IN fs WHERE f.predicate = 'issue_started' | f.object_value]),
    t.frequency = head([f IN fs WHERE f.predicate = 'frequency' | f.object_value]),
    t.severity = head([f IN fs WHERE f.predicate = 'severity' | f.object_value]),
    t.devices = [f IN fs WHERE f.predicate = 'affected_device' | f.object_value],
    t.tried = [f IN fs WHERE f.predicate = 'tried_fix' | f.object_value],
    t.router_lights = head([f IN fs WHERE f.predicate = 'router_lights' | f.object_value]),
    t.speed_reported = head([f IN fs WHERE f.predicate = 'speed_reported' | f.object_value]),
    t.connection_medium = head([f IN fs WHERE f.predicate = 'connection_medium' | f.object_value]),
    t.error_message = head([f IN fs WHERE f.predicate = 'error_message' | f.object_value])
WITH t
REMOVE t:Open, t:Resolved, t:HighPriority
FOREACH (_ IN CASE WHEN t.status = 'resolved' THEN [1] ELSE [] END | SET t:Resolved)
FOREACH (_ IN CASE WHEN t.status <> 'resolved' OR t.status IS NULL THEN [1] ELSE [] END | SET t:Open)
FOREACH (_ IN CASE WHEN t.priority = 'high' THEN [1] ELSE [] END | SET t:HighPriority)
"""

# One-time state labels for graphs written before them (idempotent; db.setup runs it).
STATE_LABELS = [
    "MATCH (f:Fact) WHERE f.active = true SET f:Current",
    "MATCH (f:Fact) WHERE f.active = false AND f.superseded_by IS NOT NULL REMOVE f:Current SET f:Superseded",
    "MATCH (f:Fact) WHERE f.active = false AND f.superseded_by IS NULL REMOVE f:Current SET f:Retired",
    "MATCH (e:Episode {speaker:'customer'}) SET e:CustomerMessage",
    "MATCH (e:Episode {speaker:'agent'}) SET e:AgentReply",
    "MATCH (e:Episode {speaker:'action'}) SET e:InternalNote",
    "MATCH (e:Episode {speaker:'noc'}) SET e:NocAlert",
    "MATCH (e:Episode) WHERE e.speaker STARTS WITH 'tool:' OR e.speaker STARTS WITH 'mcp:' SET e:ToolResult",
    "MATCH (o:Order) WHERE o.status = 'installed' REMOVE o:Pending SET o:Installed",
    "MATCH (o:Order) WHERE o.status <> 'installed' SET o:Pending",
]
CUSTOMERS_TO_LABEL = "MATCH (c:Customer) WHERE NOT c:Prospect AND NOT c:Subscriber RETURN c.name_key, c.name"
TICKETS_TO_LABEL = "MATCH (t:Entity {type:'ticket'}) WHERE NOT t:Open AND NOT t:Resolved RETURN t.name_key"

FEED_OUTAGES = """
MATCH (f:Fact {predicate:'affects', active:true, asserted_by:'resolver'})
WHERE $city IS NULL OR f.object_value = $city
RETURN f.subject, f.object_value
"""

EARLIER_SESSIONS = """
MATCH (e:Episode {customer:$c}) WHERE e.session_id <> $sid
RETURN count(e) > 0
"""

TICKET_RAISED_IN = "MATCH (t:Entity {name_key:$t}), (s:Session {session_id:$sid}) MERGE (t)-[:RAISED_IN]->(s)"

# Identity by graph match: another customer already linked to this phone / email / account node.
IDENTIFIER_OWNER = """
MATCH (me:Entity {name_key:$c})-[r:PHONE|EMAIL|ACCOUNT_ID|ALT_PHONE]->(id:Entity)<-[:PHONE|EMAIL|ACCOUNT_ID|ALT_PHONE]-(other:Customer)
WHERE other <> me
RETURN DISTINCT other.name_key, id.name_key
"""

# One customer's sessions in order, chained (Session)-[:FOLLOWED_BY]->(Session).
LINK_SESSIONS = """
MATCH (e:Episode {customer:$c})-[:IN]->(s:Session)
WITH s, min(e.recorded_at) AS t ORDER BY t
WITH collect(s) AS ss
UNWIND range(0, size(ss) - 2) AS i
WITH ss[i] AS a, ss[i + 1] AS b
MERGE (a)-[:FOLLOWED_BY]->(b)
"""

# Kavya's network check: the OLT serving this customer and anything down between it and the backbone.
NET_STATUS = """
MATCH (c:Entity {name_key:$c})-[:CONNECTED_VIA]->(o:Olt)
OPTIONAL MATCH (o)-[:UPLINK*0..3]->(n:NetNode) WHERE n.status = 'down'
RETURN o.name, collect(DISTINCT n.name)
"""
PAST_TICKETS = """
MATCH (c:Entity {name_key:$c})-[:HAS_TICKET]->(t:Entity)
OPTIONAL MATCH (st:Fact {predicate:'has_status', active:true})-[:ABOUT {role:'subject'}]->(t)
OPTIONAL MATCH (t)-[:TICKET_ABOUT]->(i:Entity)
OPTIONAL MATCH (fx:Fact {predicate:'tried_fix'})-[:ABOUT {role:'subject'}]->(t)
RETURN t.name_key, st.object_value, collect(DISTINCT i.name_key), collect(DISTINCT fx.object_value)
"""

# The world around an entity at time $t, as a multi-hop traversal over current and WAS edges, each edge valid at $t.
# GRAPH.EXPLAIN shows this range filter runs after the variable-length expansion (only inline equality maps are
# pushed into the expansion), which is fine at 2 hops; keep the hop limit low.
def world_graph_at(hops=2):
    return f"""
MATCH p = (c:Entity {{name_key:$s}})-[:{REL}|WAS*1..{int(hops)}]->(n:Entity)
WHERE all(r IN relationships(p) WHERE r.valid_from <= $t AND (r.valid_to IS NULL OR r.valid_to > $t))
RETURN [x IN nodes(p) | x.name_key], [r IN relationships(p) | coalesce(r.predicate, type(r))],
       [r IN relationships(p) | type(r) = 'WAS']
LIMIT 50
"""


# Typed edges and WAS edges for graphs written before edges carried time (idempotent).
EDGE_TIME_BACKFILL = [
    "MATCH (:Entity)-[r]->(:Entity) WHERE r.fact_id IS NOT NULL AND r.valid_from IS NULL AND type(r) <> 'WAS' "
    "MATCH (f:Fact {fact_id:r.fact_id}) SET r.valid_from = f.valid_from",
    "MATCH (f:Fact {active:false})-[:ABOUT {role:'subject'}]->(s:Entity), (f)-[:ABOUT {role:'object'}]->(o:Entity) "
    "WHERE NOT (s)-[:WAS {fact_id:f.fact_id}]->(o) "
    "CREATE (s)-[:WAS {predicate:f.predicate, fact_id:f.fact_id, valid_from:f.valid_from, valid_to:f.valid_to, "
    "ended_at:f.expired_at, ended_by:f.superseded_by}]->(o)",
]

CONFLICT_OPEN = """
MERGE (c:Conflict {conflict_id:$id})
  ON CREATE SET c.name = 'conflict: ' + $s + ' ' + $p, c.subject = $s, c.predicate = $p, c.detected_at = $at,
                c.detected_dt = localdatetime($at_dt)
SET c.status = 'open', c.resolution_policy = 'trust, then recency', c.claims = $values, c.agents = $agents,
    c.preferred = $preferred, c.resolved_at = null, c.resolution = null
REMOVE c:Resolved SET c:Open
WITH c
OPTIONAL MATCH (c)-[old:BETWEEN]->()
DELETE old
WITH DISTINCT c
UNWIND $fids AS fid
MATCH (f:Fact {fact_id:fid})
MERGE (c)-[:BETWEEN]->(f)
"""
CONFLICT_CLOSE = """
MATCH (c:Conflict {conflict_id:$id}) WHERE c.status = 'open'
SET c.status = 'resolved', c.resolved_at = $at, c.resolved_dt = localdatetime($at_dt), c.resolution = $how
REMOVE c:Open SET c:Resolved
"""

# A person settles a disagreement: the chosen claim is confirmed by the review episode (the others are retired with
# RETIRE from the same episode, then marked rejected), so the decision is provenance like any other write.
CONFIRM_CLAIM = """
MATCH (ep:Episode {episode_id:$eid}), (f:Fact {fact_id:$fid, active:true})
SET f.confirmed_by = $by, f.confirmed_at = $at, f.confirmed_dt = localdatetime($at_dt)
SET f:Confirmed
CREATE (ep)-[:CONFIRMED]->(f)
RETURN f.object_value
"""
MARK_REJECTED = """
MATCH (f:Fact) WHERE f.fact_id IN $fids
SET f.rejected = true, f.rejected_by = $eid
SET f:Rejected
"""
# Each writer's track record on one predicate, from those decisions: +1 per confirmed claim, -1 per rejected one.
TRACK_RECORD = """
MATCH (f:Fact {predicate:$p}) WHERE f.confirmed_at IS NOT NULL OR f.rejected = true
RETURN f.asserted_by, sum(CASE WHEN f.rejected = true THEN -1 ELSE 1 END)
"""

HAS_SESSION = "MATCH (c:Entity {name_key:$c}), (s:Session {session_id:$sid}) MERGE (c)-[:HAS_SESSION]->(s)"

# 4. a ticket raised to priority, with why and by whom
ESCALATE = """
MATCH (t:Entity {name_key:$t})
MERGE (e:Escalation {escalation_id:$id})
  ON CREATE SET e.name = 'escalation of ' + toUpper($t), e.reason = $reason, e.raised_by = $by, e.at = $at,
                e.at_dt = localdatetime($at_dt)
MERGE (t)-[:ESCALATED]->(e)
WITH t
OPTIONAL MATCH (c:Entity)-[:HAS_TICKET]->(t)
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | SET c.is_escalated = true)
"""

# 5. every proactive message, as a node: who got it, how, when, about what
NOTIFY = """
MATCH (c:Entity {name_key:$c})
CREATE (n:Notification {notification_id:$id, name:$kind + ' to ' + $c, kind:$kind, channel:'chat', sent_at:$at,
                        sent_dt:localdatetime($at_dt), text:$text})
CREATE (c)-[:RECEIVED]->(n)
WITH n
OPTIONAL MATCH (o:Entity {name_key:$about})
FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | MERGE (n)-[:ABOUT]->(o))
"""

# 7. an outage's own state: active, when it started, an estimated fix time, when it ended
OUTAGE_STATE = """
MATCH (o:Entity {name_key:$o})
SET o:Outage, o.active = $active,
    o.started_at = CASE WHEN $active THEN coalesce(o.started_at, $at) ELSE o.started_at END,
    o.eta = CASE WHEN $active THEN $eta ELSE null END,
    o.eta_dt = CASE WHEN $active AND $eta IS NOT NULL THEN localdatetime($eta_dt) ELSE null END,
    o.resolved_at = CASE WHEN $active THEN null ELSE $at END,
    o.resolved_dt = CASE WHEN $active THEN null ELSE localdatetime($at_dt) END
"""

# 8. a pause request as its own node, linked to the customer and the ticket that actions it
SERVICE_PAUSE = """
MATCH (c:Entity {name_key:$c}), (t:Entity {name_key:$t})
MERGE (p:ServicePause {pause_id:$id})
  ON CREATE SET p.name = 'pause for ' + $c, p.status = 'requested', p.requested_at = $at,
                p.requested_dt = localdatetime($at_dt), p.reason = $reason
MERGE (c)-[:REQUESTED]->(p)
MERGE (p)-[:FOR_TICKET]->(t)
"""

# 9. the simulator plays the personas: its sessions are attributable like any agent's work
PLAYED = "MATCH (a:Agent {agent_id:'simulator'}), (s:Session {session_id:$sid}) MERGE (a)-[:PLAYED]->(s)"

# 1-9 for graphs written before (idempotent)
LINK_BACKFILL = [
    "MATCH (e:Episode)-[:IN]->(s:Session) WHERE e.customer IS NOT NULL "
    "MATCH (c:Entity {name_key:e.customer}) MERGE (c)-[:HAS_SESSION]->(s)",
    "MATCH (e:Episode)-[:IN]->(s:Session) WITH s, max(e.recorded_at) AS last SET s.ended_at = last",
    "MATCH (f:Fact) WHERE NOT (f)-[:WRITTEN_BY]->() MATCH (a:Agent {agent_id:f.asserted_by}) MERGE (f)-[:WRITTEN_BY]->(a)",
]

# Readable profile on the Customer node itself, so FalkorDB Browser shows city/plan/order at a glance.
# Derived from the active facts after every turn; the facts stay the source of truth.
PROFILE = """
MATCH (c:Customer {name_key:$c})
OPTIONAL MATCH (f:Fact {active:true})-[:ABOUT {role:'subject'}]->(c)
WITH c, collect(f) AS fs
OPTIONAL MATCH (c)-[:PLACED]->(o:Order) WHERE o.status <> 'installed'
WITH c, fs, collect(o.plan) AS pending
// sessions where they reached out (not internal work). The label goes in WHERE: as a pattern label on the end of
// this reversed hop, FalkorDB didn't filter on it (counted the resolver's work sessions too).
OPTIONAL MATCH (c)-[:HAS_SESSION]->(ses:Session)<-[:IN]-(msg) WHERE msg:CustomerMessage
WITH c, fs, pending, count(DISTINCT ses) AS sessions
OPTIONAL MATCH (c)-[:HAS_TICKET]->(:Entity)-[:TICKET_ABOUT]->(iss:Entity)
WITH c, fs, pending, sessions, iss, count(iss) AS n
WITH c, fs, pending, sessions, max(n) AS same_issue
SET c.name = $name, c.city = head([f IN fs WHERE f.predicate = 'lives_in' | f.object_value]),
    c.plan = head([f IN fs WHERE f.predicate = 'on_plan' | f.object_value]),
    c.moving_to = head([f IN fs WHERE f.predicate = 'moving_to' | f.object_value]),
    c.budget = head([f IN fs WHERE f.predicate = 'budget' | f.object_value]),
    c.address = head([f IN fs WHERE f.predicate = 'address' | f.object_value]),
    c.router = head([f IN fs WHERE f.predicate = 'has_router' | f.object_value]),
    c.phone = head([f IN fs WHERE f.predicate = 'phone' | f.object_value]),
    c.email = head([f IN fs WHERE f.predicate = 'email' | f.object_value]),
    c.account_id = head([f IN fs WHERE f.predicate = 'account_id' | f.object_value]),
    c.connection_type = head([f IN fs WHERE f.predicate = 'connection_type' | f.object_value]),
    c.installed_at = head([f IN fs WHERE f.predicate = 'installed_at' | f.object_value]),
    c.addons = [f IN fs WHERE f.predicate = 'has_addon' | f.object_value],
    c.churn_risk = size([f IN fs WHERE f.predicate = 'service_request' AND f.object_value = 'cancellation request']) > 0,
    c.open_tickets = size([f IN fs WHERE f.predicate = 'has_ticket']),
    c.pending_order = head(pending), c.facts = size(fs), c.last_seen = coalesce($at, c.last_seen),
    c.last_seen_dt = CASE WHEN $at_dt IS NULL THEN c.last_seen_dt ELSE localdatetime($at_dt) END,
    c.contact_count = sessions, c.same_issue_count = coalesce(same_issue, 0),
    c.preferred_language = head([f IN fs WHERE f.predicate = 'preferred_language' | f.object_value]),
    c.preferred_channel = head([f IN fs WHERE f.predicate = 'prefers_channel' | f.object_value]),
    c.waitlist_area = head([f IN fs WHERE f.predicate = 'on_waitlist' | f.object_value])
WITH c
REMOVE c:Prospect, c:Subscriber, c:ChurnRisk, c:Business
FOREACH (_ IN CASE WHEN c.plan IS NULL THEN [1] ELSE [] END | SET c:Prospect)
FOREACH (_ IN CASE WHEN c.plan IS NOT NULL THEN [1] ELSE [] END | SET c:Subscriber)
FOREACH (_ IN CASE WHEN c.churn_risk THEN [1] ELSE [] END | SET c:ChurnRisk)
FOREACH (_ IN CASE WHEN c.connection_type = 'business' THEN [1] ELSE [] END | SET c:Business)
"""

SHARING_CROSSINGS = """
MATCH (a:Agent)-[c:CONSULTED]->(f:Fact) WHERE f.asserted_by <> a.agent_id
  AND ($reader IS NULL OR a.agent_id = $reader) AND ($writer IS NULL OR f.asserted_by = $writer)
RETURN a.agent_id, f.asserted_by, f.fact_id, f.subject, f.predicate, f.object_value, c.count,
       coalesce(c.last, f.recorded_at) AS last
ORDER BY last DESC LIMIT $n
"""

CASE_EPISODES = """
MATCH (ep:Episode {customer:$c})
WHERE ep.recorded_at >= $from
OPTIONAL MATCH (ep)-[:DERIVED]->(f:Fact)
WITH ep, collect(CASE WHEN f IS NULL THEN NULL ELSE [f.fact_id, f.predicate, f.object_value] END) AS facts
RETURN ep.episode_id, ep.speaker, ep.source_agent, ep.text, ep.recorded_at, facts
ORDER BY ep.recorded_at LIMIT 80
"""
CASE_READS = """
MATCH (a:Agent)-[c:CONSULTED]->(f:Fact)
WHERE f.fact_id IN $fids AND a.agent_id <> f.asserted_by
RETURN a.agent_id, f.fact_id, f.predicate, f.object_value, f.asserted_by, c.last, c.count
"""

# ---------------------------------------------------------------- the tool catalogue (relay/tools_catalog.py)

# Name resolution before any tool query: is this name a node in the graph, and what kind?
RESOLVE_ENTITY = "MATCH (e:Entity {name_key:$k}) RETURN e.name_key, e.type LIMIT 1"
RESOLVE_NODE = """
MATCH (n:NetNode {node_id:$k}) RETURN n.node_id AS id, 'NetNode' AS label, coalesce(n.label, n.node_id) AS name
UNION
MATCH (n:LastMile {node_id:$k}) RETURN n.node_id AS id, 'LastMile' AS label, coalesce(n.label, n.node_id) AS name
"""

# World clock at $t with each fact's writers and dates: "where did she live on 5 September, by whose account".
FACTS_AT = """
MATCH (f:Fact)-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s})
WHERE f.valid_from <= $t AND (f.valid_to IS NULL OR f.valid_to > $t)
MATCH (f)<-[:DERIVED]-(:Episode)<-[:WROTE]-(a:Agent)
RETURN f.fact_id, f.subject, f.predicate, f.object_value, f.active, f.valid_from, f.valid_to, f.recorded_at,
       collect(DISTINCT a.agent_id), max(a.trust)
ORDER BY f.predicate, f.valid_from
"""

# Every active claim of one subject+predicate with its writers and trust, and the Conflict node between them.
CLAIMS = """
MATCH (f:Fact {predicate:$p, active:true})-[:ABOUT {role:'subject'}]->(:Entity {name_key:$s})
MATCH (f)<-[:DERIVED]-(ep:Episode)<-[:WROTE]-(a:Agent)
WITH f, max(a.trust) AS support, max(ep.recorded_at) AS last_seen, collect(DISTINCT a.agent_id) AS agents
OPTIONAL MATCH (c:Conflict)-[:BETWEEN]->(f)
RETURN f.fact_id, f.object_value, f.asserted_by, support, last_seen, agents, f.valid_from, f.recorded_at,
       c.conflict_id, c.status, c.resolution_policy, c.preferred
ORDER BY support DESC, last_seen DESC
"""


# Blast radius: everything that hangs below a network node within $depth hops (customers, boxes, cabinets, exchanges),
# with the path that connects each one. The label comes from RESOLVE_NODE (NetNode or LastMile), never from input.
def affected_by(label, depth):
    return f"""
MATCH p = (x)-[:CONNECTED_VIA|HAS_ONT|DROP|PON|UPLINK*1..{int(depth)}]->(n:{label} {{node_id:$n}})
WITH x, p ORDER BY length(p)
WITH x, collect(p)[0] AS p
RETURN coalesce(x.node_id, x.name_key), coalesce(x.type, labels(x)[-1]), length(p),
       [y IN nodes(p) | coalesce(y.label, y.name, y.node_id, y.name_key)], [r IN relationships(p) | type(r)]
ORDER BY length(p), coalesce(x.node_id, x.name_key) LIMIT 300
"""


# Procedures (ordered ProcStep paths) that resolved this issue before.
PROCEDURES_FOR = """
MATCH (p:Procedure)-[:RESOLVES]->(:Entity {name_key:$issue})
MATCH chain = (p)-[:FIRST]->(:ProcStep)-[:NEXT*0..]->(last:ProcStep) WHERE NOT (last)-[:NEXT]->()
RETURN p.id, [n IN nodes(chain) WHERE n:ProcStep | n.action], p.successes, p.failures, p.last_used
ORDER BY p.successes DESC LIMIT 10
"""

# Runtime picks for the one-click demos (read-only): a subject whose fact changed, a disputed claim, a busy exchange.
DEMO_CHANGED = """
MATCH (old:Fact {active:false})-[:ABOUT {role:'subject'}]->(c:Entity {type:'customer'})
WHERE old.valid_to IS NOT NULL AND old.predicate <> 'awaiting'
MATCH (new:Fact {predicate:old.predicate, active:true})-[:ABOUT {role:'subject'}]->(c)
RETURN c.name_key, old.predicate, old.object_value, old.valid_from, new.object_value, new.valid_from
ORDER BY CASE old.predicate WHEN 'lives_in' THEN 0 ELSE 1 END, new.valid_from DESC LIMIT 1
"""
DEMO_KNOWN = """
MATCH (f:Fact {predicate:'lives_in', active:true})-[:ABOUT {role:'subject'}]->(c:Entity {type:'customer'})
RETURN c.name_key, f.object_value, f.valid_from ORDER BY f.valid_from ASC LIMIT 1
"""
DEMO_CONFLICT = """
MATCH (c:Conflict) WHERE size(c.claims) > 1
RETURN c.subject, c.predicate ORDER BY CASE c.status WHEN 'open' THEN 0 ELSE 1 END, c.detected_at DESC LIMIT 1
"""
DEMO_EXCHANGE = """
MATCH (c:Entity {type:'customer'})-[:CONNECTED_VIA|HAS_ONT|DROP|PON|UPLINK*1..4]->(p:Pop)
WITH p, count(DISTINCT c) AS n ORDER BY n DESC, p.node_id LIMIT 1
RETURN p.node_id, coalesce(p.label, p.node_id), n
"""
