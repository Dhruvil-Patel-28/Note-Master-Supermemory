"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReactNode } from "react";

function scrollToSource(index: number) {
  const el = document.getElementById(`source-chip-${index}`);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("ring-2", "ring-primary", "ring-offset-2");
    setTimeout(() => el.classList.remove("ring-2", "ring-primary", "ring-offset-2"), 1500);
  }
}

const CITATION_RE = /\[(\d+)\]/g;

function renderCitedText(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  CITATION_RE.lastIndex = 0;
  while ((match = CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const num = parseInt(match[1], 10);
    parts.push(
      <sup
        key={`cite-${match.index}`}
        className="cursor-pointer text-primary font-semibold hover:underline"
        onClick={() => scrollToSource(num - 1)}
        title={`Jump to source ${match[1]}`}
      >
        [{match[1]}]
      </sup>
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts;
}

function CitedParagraph({ children, ...rest }: { children?: ReactNode } & React.HTMLAttributes<HTMLParagraphElement>) {
  if (typeof children !== "string") return <p className="leading-relaxed" {...rest}>{children}</p>;
  return <p className="leading-relaxed" {...rest}>{renderCitedText(children)}</p>;
}

export default function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown-body space-y-1.5 text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ ...props }) => (
            <a {...props} className="text-primary underline underline-offset-2" target="_blank" rel="noreferrer" />
          ),
          strong: ({ ...props }) => <strong className="font-semibold" {...props} />,
          ul: ({ ...props }) => <ul className="ml-4 list-disc space-y-1" {...props} />,
          ol: ({ ...props }) => <ol className="ml-4 list-decimal space-y-1" {...props} />,
          li: ({ ...props }) => <li className="leading-relaxed" {...props} />,
          p: ({ ...props }) => <CitedParagraph {...props} />,
          code: ({ ...props }) => (
            <code
              className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"
              {...props}
            />
          ),
          pre: ({ ...props }) => (
            <pre
              className="overflow-x-auto rounded-lg border bg-muted/50 p-3 font-mono text-xs leading-relaxed"
              {...props}
            />
          ),
          blockquote: ({ ...props }) => (
            <blockquote className="border-l-2 border-muted-foreground/30 pl-3 text-muted-foreground" {...props} />
          ),
          h1: ({ ...props }) => <h1 className="text-base font-semibold" {...props} />,
          h2: ({ ...props }) => <h2 className="text-[0.95rem] font-semibold" {...props} />,
          h3: ({ ...props }) => <h3 className="text-sm font-semibold" {...props} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}