import type { ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Renders model output as formatted text.
 *
 * Without this the answer arrives as raw markup — literal asterisks around
 * every heading and backtick fences around every code block — which is the
 * single biggest thing making generated output look unfinished.
 *
 * react-markdown parses to React elements rather than injecting HTML, so
 * model output can never introduce markup into the page. That matters here
 * more than usual: the text may come from a document someone uploaded, and an
 * uploaded file is untrusted input.
 *
 * Both packages are bundled at build time. Nothing is fetched at runtime.
 */

type Props = { children: string }

export default function Markdown({ children }: Props) {
  return (
    <div className="flex flex-col gap-3 text-[15px] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (p) => <h3 className="font-heading text-[19px] leading-snug" {...p} />,
          h2: (p) => <h3 className="font-heading text-[17px] leading-snug" {...p} />,
          h3: (p) => <h4 className="font-heading text-[16px] leading-snug" {...p} />,
          h4: (p) => <h5 className="text-[15px] font-semibold" {...p} />,
          p: (p) => <p className="leading-relaxed" {...p} />,
          ul: (p) => <ul className="flex flex-col gap-1.5 pl-5 [&>li]:list-disc" {...p} />,
          ol: (p) => <ol className="flex flex-col gap-1.5 pl-5 [&>li]:list-decimal" {...p} />,
          li: (p) => <li className="pl-1 leading-relaxed marker:text-muted-foreground" {...p} />,
          strong: (p) => <strong className="font-semibold" {...p} />,
          em: (p) => <em className="italic" {...p} />,
          hr: () => <hr className="border-border" />,
          blockquote: (p) => (
            <blockquote
              className="border-l-2 border-brand/50 pl-3 text-muted-foreground"
              {...p}
            />
          ),
          a: (p) => (
            // Model output may contain links to places this machine cannot
            // reach. They stay visible but open nowhere dangerous.
            <a className="text-brand underline underline-offset-2"
               rel="noreferrer noopener" target="_blank" {...p} />
          ),
          code: ({ className, children, ...rest }: ComponentPropsWithoutRef<'code'>) => {
            // react-markdown gives fenced blocks a language class and inline
            // code none; that is the only reliable way to tell them apart.
            const fenced = /language-/.test(className ?? '')
            if (!fenced) {
              return (
                <code
                  className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[13px]"
                  {...rest}
                >
                  {children}
                </code>
              )
            }
            return (
              <code className="font-mono text-[12.5px] leading-relaxed" {...rest}>
                {children}
              </code>
            )
          },
          pre: (p) => (
            <pre
              className="overflow-x-auto rounded-xl border border-border bg-muted/40 px-4 py-3"
              {...p}
            />
          ),
          table: (p) => (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]" {...p} />
            </div>
          ),
          th: (p) => (
            <th
              className="border-b border-border px-2.5 py-1.5 text-left font-medium"
              {...p}
            />
          ),
          td: (p) => <td className="border-b border-border/60 px-2.5 py-1.5" {...p} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
