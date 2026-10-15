import { describe, expect, it } from 'vitest'
import { fromEvent, fromLearned, launch, settle, type Chip } from './chips'
import type { RelayEvent } from './types'

const ev = (type: string, data: unknown) => ({ type, data } as RelayEvent)
const who = 'alice rao'

describe('memory chips', () => {
  it('holds socket facts while a message is in flight, then flies them from the reply and settles', () => {
    const tickets = new Set<string>()
    let cs: Chip[] = []
    cs = fromEvent(cs, ev('fact_created', { fact_id: 'f1', subject: who, predicate: 'lives_in', object: 'mumbai', agent: 'intake' }), who, tickets, 'settled')
    cs = fromEvent(cs, ev('fact_created', { fact_id: 'f2', subject: who, predicate: 'lives_in', object: 'pune', agent: 'intake' }), who, tickets, 'pending')
    cs = fromEvent(cs, ev('fact_superseded', { fact_id: 'f2', old_fact_id: 'f1', subject: who, predicate: 'lives_in', object: 'pune', old_object: 'mumbai', agent: 'intake' }), who, tickets, 'pending')
    expect(cs.map((c) => [c.key, c.status, c.phase])).toEqual([['f2', 'updated', 'pending']]) // old value replaced, not duplicated

    // The POST reply repeats it as learned: no duplicate, status kept.
    cs = fromLearned(cs, [{ fact_id: 'f2', subject: who, predicate: 'lives_in', object: 'pune', status: 'updated', replaced: [{ fact_id: 'f1', object: 'mumbai' }] }], 'pending')
    expect(cs).toHaveLength(1)
    cs = launch(cs, 'reply-1', ['f2'])
    expect(cs[0]).toMatchObject({ phase: 'flying', line: 'reply-1' })
    cs = settle(cs, 'reply-1')
    expect(cs[0].phase).toBe('settled')
    expect(cs[0].note).toBe('was Mumbai')
  })

  it('tracks the customer\'s tickets, ignores other customers, renders retirements', () => {
    const tickets = new Set<string>()
    let cs: Chip[] = []
    cs = fromEvent(cs, ev('ticket_opened', { ticket: 'PML-2051', customer: who, issue: 'evening wifi drops' }), who, tickets, 'settled')
    cs = fromEvent(cs, ev('ticket_status', { ticket: 'PML-2051', status: 'in progress' }), who, tickets, 'settled')
    cs = fromEvent(cs, ev('fact_created', { fact_id: 'x', subject: 'bob mehta', predicate: 'lives_in', object: 'pune', agent: 'intake' }), who, tickets, 'settled')
    cs = fromEvent(cs, ev('fact_retired', { fact_id: 'f9', subject: who, predicate: 'lives_in', object: 'chennai', agent: 'intake' }), who, tickets, 'settled')
    expect(cs.map((c) => c.label)).toEqual(['ticket PML-2051 opened', 'PML-2051 is in progress', 'no longer lives in Chennai'])
    expect(cs[2].status).toBe('retired')
  })
})

describe('internal facts', () => {
  it('stay out of the customer panel', () => {
    const e = { type: 'fact_created', data: { fact_id: 'f1', subject: 'chandran', predicate: 'awaiting', object: 'waitlist:goa', agent: 'intake' } } as const
    expect(fromEvent([], e as never, 'chandran', new Set(), 'settled')).toEqual([])
    expect(fromLearned([], [{ fact_id: 'f2', subject: 'chandran', predicate: 'doesnt_know', object: 'router', status: 'new' }], 'settled')).toEqual([])
  })
})
