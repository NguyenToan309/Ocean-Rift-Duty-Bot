import * as React from 'react';
import { cn } from '../../lib/cn';
import { ChevronDown } from 'lucide-react';

/**
 * Lightweight native <select> wrapper — keeps logic simple,
 * works with keyboard, accessible by default.
 */
export interface NativeSelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

export const NativeSelect = React.forwardRef<HTMLSelectElement, NativeSelectProps>(
  ({ className, children, ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          'flex h-9 w-full appearance-none rounded-lg border border-[var(--border)] bg-[var(--input-background)] px-3 pr-8 py-1 text-sm shadow-sm',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'cursor-pointer',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 pointer-events-none text-[var(--muted-foreground)]" />
    </div>
  ),
);
NativeSelect.displayName = 'NativeSelect';
