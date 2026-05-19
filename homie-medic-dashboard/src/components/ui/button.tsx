import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/cn';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'bg-[var(--primary)] text-[var(--primary-foreground)] shadow-sm hover:brightness-110 hover:-translate-y-px active:translate-y-0',
        destructive:
          'bg-[var(--destructive)] text-[var(--destructive-foreground)] shadow-sm hover:brightness-110',
        success:
          'bg-[var(--success)] text-[var(--success-foreground)] shadow-sm hover:brightness-110',
        outline:
          'border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--muted)] hover:border-[var(--primary)]',
        secondary:
          'bg-[var(--secondary)] text-[var(--secondary-foreground)] hover:brightness-95',
        ghost: 'hover:bg-[var(--muted)] text-[var(--foreground)]',
        link: 'text-[var(--primary)] underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2 [&_svg]:size-4',
        sm: 'h-8 px-3 text-xs [&_svg]:size-3.5',
        lg: 'h-10 px-6 text-base [&_svg]:size-5',
        icon: 'h-9 w-9 [&_svg]:size-4',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />;
  },
);
Button.displayName = 'Button';

export { buttonVariants };
