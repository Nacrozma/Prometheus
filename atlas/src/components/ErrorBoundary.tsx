import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./ui/primitives";

/** Keeps one failing view from blanking the whole window; shows what failed and offers recovery. */
export class ErrorBoundary extends Component<{ children: ReactNode; label: string }, { error: Error | null }> {
  override state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[atlas] ${this.props.label} crashed`, error, info.componentStack);
  }

  override render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="grid h-full place-items-center p-8">
        <div className="max-w-lg rounded-xl border border-[color:var(--err)]/30 bg-bg-2 p-6 text-center shadow-3">
          <p className="font-display text-md font-semibold">{this.props.label} hit an unexpected error</p>
          <p className="mt-2 break-words font-mono text-xs text-text-2">{this.state.error.message}</p>
          <p className="mt-2 text-xs text-text-3">Your data is safe. Other parts of Atlas keep working.</p>
          <Button className="mt-4" variant="primary" onClick={() => this.setState({ error: null })}>
            Try again
          </Button>
        </div>
      </div>
    );
  }
}
