"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
          p: ({ ...props }) => <p className="leading-relaxed" {...props} />,
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