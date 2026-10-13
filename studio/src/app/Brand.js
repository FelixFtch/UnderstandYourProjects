import { jsx as _jsx } from "react/jsx-runtime";
import { cx } from "../design/primitives";
export function Monogram({ size = 36, className }) {
    return (_jsx("span", { "aria-hidden": "true", className: cx("grid shrink-0 place-items-center rounded-[30%] bg-ink font-serif text-canvas italic select-none", className), style: { width: size, height: size, fontSize: Math.round(size * 0.56), lineHeight: 1 }, children: "J" }));
}
