import { describe, expect, it } from 'vitest'
import { asksSomething, introKind, nameFrom, saysMore } from '../components/portal/SupportChat'

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

describe('a message sent before the name', () => {
  it('is held and answered later only when it asks something', () => {
    for (const hi of ['Hi there', 'hello there!', 'Hey team', 'hi, how are you?', 'Good morning', 'hello WiFight', 'hey there, can you help'])
      expect(asksSomething(hi), hi).toBe(false)
    for (const q of ['my wifi is slow', 'internet not working', 'Hi there, my internet keeps dropping', 'do you have fiber in Pune?'])
      expect(asksSomething(q), q).toBe(true)
  })
})

describe('the company and the bot are never your name', () => {
  it('reads "I am a WiFight user" as one of ours, not as a name', () => {
    for (const m of ['hey im a wifight user', "Hey I'm a WiFight user", 'hey im wifight user', 'hi wifight', 'hey wifight team',
      'hey mr.fix-it', 'thanks mr fix it', 'my name is wifight', 'hey im back'])
      expect(nameFrom(m), m).toBeNull()
    expect(nameFrom('I am Rupesh, a WiFight user')).toBe('rupesh')
    expect(nameFrom("I'm Tharun from WiFight")).toBe('tharun')
  })
  it('answers the first message in a way that fits it', () => {
    expect(introKind('hey im a wifight user')).toBe('member')
    expect(introKind('I already have an account')).toBe('member')
    expect(introKind('hey im back')).toBe('member')
    expect(introKind('hi wifight')).toBe('greeting')
    expect(introKind('Hi there')).toBe('greeting')
    expect(introKind("I'm a wifight user and my internet is down")).toBe('question')  // held, answered after the name
  })
})
