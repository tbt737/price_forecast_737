import Link from "next/link";

export function Breadcrumb({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-sm text-muted">
      {items.map((it, i) => (
        <span key={`${it.label}-${i}`} className="flex items-center gap-1.5">
          {i > 0 ? (
            <span aria-hidden className="text-subtle">
              /
            </span>
          ) : null}
          {it.href ? (
            <Link href={it.href} className="transition-colors hover:text-text hover:underline">
              {it.label}
            </Link>
          ) : (
            <span aria-current="page" className="font-medium text-text">
              {it.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}
