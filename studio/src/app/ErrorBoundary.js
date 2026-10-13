import { jsx as _jsx } from "react/jsx-runtime";
import { Component } from "react";
import { ErrorState } from "../design/primitives";
/** Keeps a crashing view from taking the shell down. Reset by changing `key`. */
export class ErrorBoundary extends Component {
    state = { error: null };
    static getDerivedStateFromError(error) {
        return { error };
    }
    componentDidCatch(error, info) {
        console.error("[studio] view crashed", error, info.componentStack);
    }
    render() {
        if (this.state.error) {
            return (_jsx(ErrorState, { className: "h-full", title: "This view hit a problem", error: this.state.error, onRetry: () => this.setState({ error: null }) }));
        }
        return this.props.children;
    }
}
