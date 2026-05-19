import * as React from 'react';
import { cn } from '../../lib/cn';

export interface AvatarProps extends React.HTMLAttributes<HTMLDivElement> {
  src?: string | null;
  alt?: string;
  fallback?: string;
  size?: number;
}

export function Avatar({ src, alt, fallback, size = 36, className, ...props }: AvatarProps) {
  const [errored, setErrored] = React.useState(false);
  const showImage = src && !errored;
  const initials = (fallback || alt || '?').slice(0, 2).toUpperCase();

  return (
    <div
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-[var(--muted)] text-xs font-semibold text-[var(--muted-foreground)] ring-1 ring-[var(--border)]',
        className,
      )}
      style={{ width: size, height: size }}
      {...props}
    >
      {showImage ? (
        <img
          src={src}
          alt={alt}
          className="h-full w-full object-cover"
          onError={() => setErrored(true)}
        />
      ) : (
        <span style={{ fontSize: size * 0.4 }}>{initials}</span>
      )}
    </div>
  );
}
