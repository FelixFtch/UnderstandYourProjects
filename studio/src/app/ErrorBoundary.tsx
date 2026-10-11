import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorState } from "../design/primitives";

interface State { error: Error | null }

/** Keeps a crashing view from taking the shell down. Reset by changing `key`. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[studio] view crashed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorState
          className="h-full"
          title="This view hit a problem"
          error={this.state.error}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
