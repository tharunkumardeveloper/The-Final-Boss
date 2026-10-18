import { describe, expect, it } from 'vitest'
import { grade, matches, norm, type Gradable, type QuestionSpec } from './grade'
// the published run and its questions, straight from the repository
import resultsJson from '../../../eval/results.json'
import questionsJson from '../../../data/questions.json'

type Row = Gradable & { i: number; question_id: string; correct: boolean }
const results = resultsJson as unknown as { systems: Record<string, { rows: Row[] }> }
const questions = questionsJson as unknown as (QuestionSpec & { i: number })[]
const spec = (i: number) => questions.find((q) => q.i === i)!

describe('the benchmark grading rule, in the browser', () => {
  it('normalises like the Python side', () => {
    expect(norm('  Fiber_300. ')).toBe('fiber 300')
    expect(matches('Fiber 300', 'fiber 300')).toBe(true)
    expect(matches('fiber 100', 'fiber 300')).toBe(false)
  })
  it('reproduces every published grade (both systems, all 160 questions)', () => {
    let n = 0
    for (const sys of ['FULL', 'B1']) {
      for (const row of results.systems[sys].rows) {
        expect(grade(spec(row.i), row), `${sys} ${row.question_id}`).toBe(row.correct)
        n++
      }
    }
    expect(n).toBe(320)
    const k = (sys: string) => results.systems[sys].rows.filter((r) => grade(spec(r.i), r)).length
    expect([k('FULL'), k('B1')]).toEqual([159, 98])
  })
})
