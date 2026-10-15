import { Component, type ReactNode } from 'react'

/** A page that crashes while rendering shows a way back instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('page crashed:', error)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex min-h-[100dvh] items-center justify-center px-4">
        <div className="w-full max-w-md rounded-2xl bg-surface p-8 text-center shadow-lift hairline" role="alert">
          <h1 className="font-display text-xl font-semibold">Something went wrong on this page</h1>
          <p className="mt-2 text-sm text-ink-2">Your chats and memory are safe in the graph. Reloading usually fixes it.</p>
          <p className="mt-3 truncate font-mono text-[11px] text-ink-3">{this.state.error.message}</p>
          <div className="mt-6 flex justify-center gap-2">
            <button className="btn-primary" onClick={() => this.setState({ error: null })}>Try again</button>
            <button className="btn-ghost hairline" onClick={() => window.location.reload()}>Reload</button>
          </div>
        </div>
      </div>
    )
  }
}
