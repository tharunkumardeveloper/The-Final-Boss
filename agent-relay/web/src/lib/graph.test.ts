import { describe, expect, it } from 'vitest'
import { activeOutages, applyEvent, emptyGraph, loadGraph, relevantToFocus, speakerCustomer } from './graph'
import type { RelayEvent } from './types'

const ev = (type: string, data: unknown) => ({ type, data } as RelayEvent)

describe('graph reducer', () => {
  it('adds, supersedes, flags conflicts, keeps object identity', () => {
    const s = emptyGraph()
    applyEvent(s, ev('fact_created', { fact_id: 'f-1', subject: 'alice rao', predicate: 'lives_in', object: 'mumbai', agent: 'intake' }))
    const alice = s.nodes.get('e:alice rao')!
    expect(alice.kind).toBe('customer')
    expect(s.nodes.get('e:mumbai')!.kind).toBe('city')

    applyEvent(s, ev('fact_superseded', { fact_id: 'f-2', old_fact_id: 'f-1', subject: 'alice rao', predicate: 'lives_in',
      object: 'pune', old_object: 'mumbai', agent: 'intake' }))
    expect(s.edges.get('f:f-1')!.active).toBe(false)
    expect(s.edges.get('f:f-1')!.faded).toBeDefined()
    expect(s.edges.get('f:f-2')!.active).toBe(true)
    expect(s.nodes.get('e:alice rao')).toBe(alice) // stable object: layout positions survive

    applyEvent(s, ev('fact_created', { fact_id: 'f-3', subject: 'alice rao', predicate: 'on_plan', object: 'fiber 300', agent: 'intake' }))
    applyEvent(s, ev('fact_created', { fact_id: 'f-4', subject: 'alice rao', predicate: 'on_plan', object: 'fiber 100', agent: 'resolver' }))
    applyEvent(s, ev('conflict', { subject: 'alice rao', predicate: 'on_plan', claims: [
      { fact_id: 'f-3', value: 'fiber 300', agent: 'intake', trust: 0.9, preferred: true },
      { fact_id: 'f-4', value: 'fiber 100', agent: 'resolver', trust: 0.6, preferred: false }] }))
    expect(s.edges.get('f:f-3')!.conflict && s.edges.get('f:f-4')!.conflict).toBe(true)

    expect(applyEvent(s, ev('message', { session_id: 's', customer: 'alice rao', speaker: 'customer', text: 'hi' }))).toBe(false)
  })

  it('superseded edge arriving before its original still renders inactive; snapshot merges', () => {
    const s = emptyGraph()
    applyEvent(s, ev('fact_superseded', { fact_id: 'f-9', old_fact_id: 'f-8', subject: 'bob', predicate: 'on_plan',
      object: 'fiber 1000', old_object: 'fiber 300', agent: 'intake' }))
    expect(s.edges.get('f:f-8')!.active).toBe(false)
    loadGraph(s, { nodes: [{ id: 'e:bob', kind: 'customer', label: 'Bob', salience: 0.4 }], edges: [] })
    expect(s.nodes.get('e:bob')!.salience).toBe(0.4)
  })

  it('retires a fact without adding a new edge; ticket ids normalise to lowercase entity ids', () => {
    const s = emptyGraph()
    applyEvent(s, ev('fact_created', { fact_id: 'f-c', subject: 'carol dsouza', predicate: 'lives_in', object: 'chennai', agent: 'intake' }))
    const before = s.edges.size
    applyEvent(s, ev('fact_retired', { fact_id: 'f-c', subject: 'carol dsouza', predicate: 'lives_in', object: 'chennai', agent: 'intake', valid_to: '2026-09-20T10:00:00Z' }))
    expect(s.edges.size).toBe(before)
    expect(s.edges.get('f:f-c')!.active).toBe(false)
    expect(s.edges.get('f:f-c')!.faded).toBeDefined()

    applyEvent(s, ev('ticket_opened', { ticket: 'PML-2041', customer: 'alice rao', issue: 'drops' }))
    applyEvent(s, ev('fact_created', { fact_id: 'f-t', subject: 'alice rao', predicate: 'has_ticket', object: 'pml-2041', agent: 'intake' }))
    expect(s.nodes.get('e:pml-2041')!.kind).toBe('ticket')
    expect([...s.nodes.keys()].filter((k) => k.includes('2041'))).toEqual(['e:pml-2041'])
  })

  it('focus mode keeps the neighbourhood growing and ignores unrelated customers', () => {
    const s = emptyGraph()
    loadGraph(s, { nodes: [{ id: 'e:alice rao', kind: 'customer', label: 'alice rao' }, { id: 'e:pune', kind: 'city', label: 'pune' }],
      edges: [{ id: 'f:1', source: 'e:alice rao', target: 'e:pune', label: 'lives_in', active: true },
        { id: 'f:2', source: 'e:alice rao', target: 'e:pml-2041', label: 'has_ticket', active: true }] }, 123)
    expect(s.nodes.get('e:pune')!.appear).toBe(123)
    const f = (subject: string, object: string, predicate = 'owns_device') => ev('fact_created', { fact_id: 'x', subject, predicate, object, agent: 'intake' })
    expect(relevantToFocus(s, f('alice rao', 'laptop'), 'alice rao')).toBe(true)          // focused customer
    expect(relevantToFocus(s, f('pml-2041', 'in progress', 'has_status'), 'alice rao')).toBe(true) // one of her tickets
    expect(relevantToFocus(s, f('bob mehta', 'pune', 'lives_in'), 'alice rao')).toBe(true) // touches a shown node
    expect(relevantToFocus(s, f('carol dsouza', 'email', 'prefers_channel'), 'alice rao')).toBe(false)
    expect(relevantToFocus(s, ev('message', { session_id: 's', customer: 'Carol Dsouza', speaker: 'customer', text: 'hi' }), 'alice rao')).toBe(false)
    expect(relevantToFocus(s, f('carol dsouza', 'email'), null)).toBe(true) // "Everyone"
    expect(speakerCustomer(ev('message', { session_id: 's', customer: 'Tharun K', speaker: 'customer', text: 'hi' }))).toBe('tharun k')
    expect(speakerCustomer(ev('message', { session_id: 's', customer: 'Tharun K', speaker: 'intake', text: 'hi' }))).toBeNull()
  })

  it('reads active outages for the banner', () => {
    const s = emptyGraph()
    applyEvent(s, ev('fact_created', { fact_id: 'f-o', subject: 'pune east fiber cut', predicate: 'affects', object: 'pune', agent: 'resolver' }))
    expect(activeOutages(s)).toEqual([{ outage: 'pune east fiber cut', city: 'pune' }])
  })
})
