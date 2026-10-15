import { describe, expect, it } from 'vitest'
import { nameFrom, saysMore } from '../components/portal/SupportChat'

describe('nameFrom', () => {
  it('ignores greetings', () => {
    expect(nameFrom('Hi There')).toBeNull()
    expect(nameFrom('hello!')).toBeNull()
  })
  it('finds the name in a sentence', () => {
    expect(nameFrom("Hi, I'm Tharun")).toBe('tharun')
    expect(nameFrom('my name is Tharun Kumar')).toBe('tharun kumar')
    expect(nameFrom('hey there, this is Asha Rao.')).toBe('asha rao')
    expect(nameFrom('Myself Adit Raj')).toBe('adit raj')
    expect(nameFrom('hi sir, me Adit')).toBe('adit')
    expect(nameFrom('Imran Khan')).toBe('imran khan')
  })
  it('keeps a plain name', () => {
    expect(nameFrom('Tharun')).toBe('tharun')
  })
})

describe('names inside a normal chat message', () => {
  it('takes the name after a lead-in and stops at the next ordinary word', () => {
    expect(nameFrom("Hi, I'm Adit and my wifi keeps dropping")).toBe('adit')
    expect(nameFrom("hey this is Tharun Kumar from Pune")).toBe('tharun kumar')
  })
  it('does not take questions or descriptions as names', () => {
    expect(nameFrom('do you cover goa?')).toBeNull()
    expect(nameFrom("I'm in Goa")).toBeNull()
    expect(nameFrom("Im a gamer and yt content creator living in goa")).toBeNull()
    expect(nameFrom('my wifi drops every evening')).toBeNull()
    expect(nameFrom('hello')).toBeNull()
  })
  it('knows when the message said more than the name', () => {
    expect(saysMore("Hi, I'm Adit and my wifi keeps dropping", 'adit')).toBe(true)
    expect(saysMore('Adit Raj', 'adit raj')).toBe(false)
    expect(saysMore("hi, I'm Adit", 'adit')).toBe(false)
  })
})
