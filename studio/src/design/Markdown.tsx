// Markdown renderer shared by Jarvis replies, project overviews and answers.
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cx } from "./primitives";

const components: Components = {
  a({ href, children, ...rest }) {
    const external = !!href && /^https?:/i.test(href);
    return (
      <a href={href} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})} {...rest}>
        {children}
      </a>
    );
  },
};

export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cx("j-prose", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
        {text}
      </ReactMarkdown>
    </div>
  );
}
