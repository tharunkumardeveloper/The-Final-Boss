import { afterAll, describe, expect, it, vi } from 'vitest'
import { mergeUsage, quotaState } from '../components/console/useConsole'
import { emptyGraph, applyEvent, activeOutages } from './graph'
import { mockRequest, subscribeMock } from './mock'
import type { AskResponse, Card, ChatResponse, Clock, Conversation, Graph, RelayEvent, Stats, Ticket, UsagePayload } from './types'

vi.useFakeTimers()
afterAll(() => vi.useRealTimers())

const call = async <T>(path: string, body?: unknown, method = 'POST') => {
  const p = mockRequest(path, body ? { method, body: JSON.stringify(body) } : undefined) as Promise<T>
  await vi.advanceTimersByTimeAsync(2000)
  return p
}

describe('mock backend replays the story consistently', () => {
  it('drives graph, clocks, conflict, path, retirement, conversation and usage', async () => {
    const ui = emptyGraph()
    const events: RelayEvent[] = []
    const stop = subscribeMock((e) => { applyEvent(ui, e); events.push(e) })
    await vi.advanceTimersByTimeAsync(200_000) // whole script
    const types = events.map((e) => e.type)

    // Contract: fact_created precedes each fact_superseded for the same new fact; supersede carries timestamps.
    const sup = events.findIndex((e) => e.type === 'fact_superseded' && e.data.fact_id === 'f-a7')
    expect(events.findIndex((e) => e.type === 'fact_created' && e.data.fact_id === 'f-a7')).toBeLessThan(sup)
    expect((events[sup].data as { valid_from?: string }).valid_from).toBeTruthy()
    expect(types).toContain('conflict')
    expect(types).toContain('usage')
    expect(ui.edges.get('f:f-a1')?.active).toBe(false)
    expect(ui.edges.get('f:f-c3')?.active).toBe(false) // Carol no longer in Bengaluru (retired)
    expect(activeOutages(ui)).toEqual([{ outage: 'pune east fiber cut', city: 'pune' }])

    const stats = await call<Stats>('/api/tenants/pml/stats')
    expect(stats.conflicts).toBe(1)
    const tickets = await call<Ticket[]>('/api/tenants/pml/tickets')
    expect(tickets.map((t) => t.ticket)).toContain('PML-2041')

    // Backdated move: moved on the 10th, told on the 12th. On the 11th the clocks disagree.
    const c = await call<Clock>('/api/tenants/pml/clock?subject=alice%20rao&at=2026-09-11T12:00:00%2B05:30')
    expect(c.world.find((r) => r.predicate === 'lives_in')?.value).toBe('pune')
    expect(c.belief.find((r) => r.predicate === 'lives_in')?.value).toBe('mumbai')

    const a = await call<AskResponse>('/api/tenants/pml/ask', { question: 'Which plan is Alice Rao on?' })
    expect(a.conflict).toBe(true)
    expect(a.path.edges.some((e) => e.label === 'DERIVED')).toBe(true)

    const card = await call<Card>('/api/tenants/pml/card/f%3Af-a7')
    expect(card.active).toBe(true)
    expect(card.lines.join(' ')).toContain('Replaced Mumbai')
    const retired = await call<Card>('/api/tenants/pml/card/f%3Af-c3')
    expect(retired.active).toBe(false)
    expect(retired.lines.join(' ')).toContain('No longer true')

    // Conversation history + session continuity
    const conv = await call<Conversation>('/api/tenants/pml/conversation?customer=alice%20rao')
    expect(conv.sessions.map((s) => s.session_id)).toEqual(expect.arrayContaining(['alice-s1', 'alice-s2']))
    expect(conv.sessions[0].summary).toBeTruthy()
    const r1 = await call<ChatResponse>('/api/tenants/pml/chat', { customer: 'Carol Dsouza', text: 'Please use WhatsApp again' })
    expect(r1.session_id).toMatch(/^carol-dsouza-web-\d{8}$/)
    expect(r1.learned[0]).toMatchObject({ predicate: 'prefers_channel', object: 'whatsapp', status: 'updated' })
    const r2 = await call<ChatResponse>('/api/tenants/pml/chat', { customer: 'Carol Dsouza', text: 'I am no longer in Chennai either', session_id: r1.session_id })
    expect(r2.session_id).toBe(r1.session_id)
    const carol = await call<Conversation>('/api/tenants/pml/conversation?customer=carol%20dsouza')
    expect(carol.sessions.find((s) => s.session_id === r1.session_id)?.messages.length).toBe(4)

    // A new customer's problem report opens a ticket (portal toast) and Kavya answers plan questions from memory.
    const dev = await call<ChatResponse>('/api/tenants/pml/chat', { customer: 'Dev Kulkarni', text: 'My wifi drops every evening, mostly on my PS5.' })
    expect(dev.ticket_opened).toMatch(/^PML-\d{4}$/)
    expect(dev.learned.map((l) => l.predicate)).toEqual(expect.arrayContaining(['owns_device', 'reported_issue', 'has_ticket']))
    const plan = await call<ChatResponse>('/api/tenants/pml/chat', { customer: 'Alice Rao', text: 'Which plan am I on?' })
    expect(plan.reply).toMatch(/Fiber 300.*Fiber 100/)

    // /chat returns both episode ids, so the portal collapses the socket copy and the reply into one bubble.
    expect(dev.episode_id).toBeTruthy()
    expect(dev.reply_episode_id).toBeTruthy()
    expect(dev.reply_episode_id).not.toBe(dev.episode_id)

    // Focused graph: Alice's 1-hop neighbourhood has her city and ticket but not Carol; 2 hops reaches Bob via Pune.
    const g1 = await call<Graph>('/api/tenants/pml/graph?focus=e%3Aalice%20rao&depth=1')
    const ids1 = g1.nodes.map((n) => n.id)
    expect(ids1).toEqual(expect.arrayContaining(['e:alice rao', 'e:pune', 'e:pml-2041']))
    expect(ids1).not.toContain('e:carol dsouza')
    expect(ids1).not.toContain('e:bob mehta')
    const g2 = await call<Graph>('/api/tenants/pml/graph?focus=e%3Aalice%20rao&depth=2')
    expect(g2.nodes.map((n) => n.id)).toContain('e:bob mehta')
    expect(g2.edges.every((e) => g2.nodes.some((n) => n.id === e.source) && g2.nodes.some((n) => n.id === e.target))).toBe(true)

    // Usage: payload, PUT limits, PUT routes, live merge
    const u = await call<UsagePayload>('/api/usage')
    expect(quotaState(u).exhausted).toBe(1)
    const raised = await call<UsagePayload>('/api/usage/limits', { model: 'openai/gpt-oss-120b', tpd: 400_000, rpd: 2000 }, 'PUT')
    expect(quotaState(raised).exhausted).toBe(0)
    const routed = await call<UsagePayload>('/api/usage/routes', { job: 'answer', models: ['qwen/qwen3.8-27b'] }, 'PUT')
    expect(routed.routes.answer).toEqual(['qwen/qwen3.8-27b'])
    expect(routed.models.find((m) => m.model === 'openai/gpt-oss-120b')!.jobs).not.toContain('answer')
    const bumped = { ...routed.models[0], used: { ...routed.models[0].used, requests: 999 } }
    expect(mergeUsage(routed, bumped)!.models[0].used.requests).toBe(999)
    stop()
  })
})
