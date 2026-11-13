import { Component, type ReactNode } from "react";
import { Notice, Button } from "../components/ui";

/** A crash in one part of the page shows a message there instead of a blank
 *  page, and the rest keeps working. */
export class ErrorBoundary extends Component<
  { children: ReactNode; message: string; reloadLabel: string },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("[dashboard]", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <Notice tone="danger" className="u-mb-16"
              action={<Button size="sm" onClick={() => window.location.reload()}>{this.props.reloadLabel}</Button>}>
        {this.props.message}
      </Notice>
    );
  }
}
