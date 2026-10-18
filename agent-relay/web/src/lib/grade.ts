// The benchmark's grading rule, the same as eval/run_eval.py (score, _match) and relay/memory.py (norm), so anyone can
// re-grade the published answers in the browser, or grade a live re-run of a question, and get the same verdict.

export interface Gradable { values: string[]; unknown?: boolean; conflict?: boolean; error?: boolean }
export interface QuestionSpec { gold: string[]; expect_unknown?: boolean; expect_conflict?: boolean }

export const norm = (s: unknown) => String(s ?? '').toLowerCase().replace(/_/g, ' ').split(/\s+/).filter(Boolean).join(' ')
  .replace(/^[ .,'"]+|[ .,'"]+$/g, '')

/** A predicted value matches a gold one: equal, or one contains the other (the prediction at least 3 characters). */
export function matches(pred: string, gold: string): boolean {
  const p = norm(pred), g = norm(gold)
  return !!p && (p === g || p.includes(g) || (p.length >= 3 && g.includes(p)))
}

/** Correct or not, exactly as the published run scored it. */
export function grade(q: QuestionSpec, a: Gradable): boolean {
  if (a.error) return false
  const vals = (a.values ?? []).filter((v) => norm(v))
  if (q.expect_unknown) return !!(a.unknown || !vals.length)
  if (a.unknown || !vals.length) return false
  if (q.expect_conflict) return !!a.conflict && matches(vals[0], q.gold[0])
  return q.gold.every((g) => vals.some((v) => matches(v, g))) && vals.every((v) => q.gold.some((g) => matches(v, g)))
}
