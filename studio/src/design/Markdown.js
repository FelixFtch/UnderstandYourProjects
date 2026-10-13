import { jsx as _jsx } from "react/jsx-runtime";
// Markdown renderer shared by Jarvis replies, project overviews and answers.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cx } from "./primitives";
const components = {
    a({ href, children, ...rest }) {
        const external = !!href && /^https?:/i.test(href);
        return (_jsx("a", { href: href, ...(external ? { target: "_blank", rel: "noreferrer noopener" } : {}), ...rest, children: children }));
    },
};
export function Markdown({ text, className }) {
    return (_jsx("div", { className: cx("j-prose", className), children: _jsx(ReactMarkdown, { remarkPlugins: [remarkGfm], components: components, skipHtml: true, children: text }) }));
}
