import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/cn';

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-[var(--primary)]/10 text-[var(--primary)]',
        secondary: 'border-transparent bg-[var(--secondary)] text-[var(--secondary-foreground)]',
        destructive: 'border-transparent bg-[var(--destructive)]/10 text-[var(--destructive)]',
        success: 'border-transparent bg-[var(--success)]/10 text-[var(--success)]',
        warning: 'border-transparent bg-[var(--warning)]/10 text-[var(--warning)]',
        info: 'border-transparent bg-[var(--info)]/10 text-[var(--info)]',
        outline: 'border-[var(--border)] text-[var(--foreground)]',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
