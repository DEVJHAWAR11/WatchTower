"use client";

import { Dialog as D, DropdownMenu as DM, Switch as Sw, Tabs as T, Tooltip as Tt } from "radix-ui";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

// ------------------------------------------------------------------ Dialog
export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({
  title,
  description,
  children,
  className,
  wide,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  wide?: boolean;
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-[rgb(10_14_12/0.45)] backdrop-blur-[2px] data-[state=open]:animate-[fade-in_160ms_ease-out]" />
      <D.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 max-h-[90dvh] overflow-x-hidden w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto border border-line-strong bg-elevated p-6 shadow-float focus:outline-none data-[state=open]:animate-[dialog-in_200ms_cubic-bezier(.2,.8,.2,1)] sm:p-7",
          wide ? "max-w-2xl" : "max-w-md",
          className,
        )}
      >
        <div className="mb-5 pr-8">
          <D.Title className="font-display text-[28px] leading-tight text-ink">{title}</D.Title>
          {description ? <D.Description className="mt-1.5 text-sm text-ink-2">{description}</D.Description> : <D.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</D.Description>}
        </div>
        {children}
        <D.Close
          className="absolute right-4 top-4 grid h-8 w-8 place-items-center rounded-[3px] text-ink-3 transition hover:bg-sunken hover:text-ink"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </D.Close>
      </D.Content>
    </D.Portal>
  );
}

// ------------------------------------------------------------------ Dropdown
export const Menu = DM.Root;
export const MenuTrigger = DM.Trigger;

export function MenuContent({ children, align = "end", className }: { children: React.ReactNode; align?: "start" | "end" | "center"; className?: string }) {
  return (
    <DM.Portal>
      <DM.Content
        align={align}
        sideOffset={6}
        className={cn(
          "z-50 min-w-[200px] border border-line-strong bg-elevated p-1 shadow-float data-[state=open]:animate-[menu-in_140ms_ease-out]",
          className,
        )}
      >
        {children}
      </DM.Content>
    </DM.Portal>
  );
}

export function MenuItem({
  children,
  onSelect,
  danger,
  disabled,
  icon,
}: {
  children: React.ReactNode;
  onSelect?: (e: Event) => void;
  danger?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <DM.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer select-none items-center gap-2.5 rounded-[2px] px-2.5 py-2 text-sm outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-45 data-[highlighted]:bg-sunken",
        danger ? "text-err" : "text-ink",
      )}
    >
      {icon && <span className="text-ink-3 [&>svg]:h-4 [&>svg]:w-4">{icon}</span>}
      {children}
    </DM.Item>
  );
}

export function MenuSeparator() {
  return <DM.Separator className="my-1 h-px bg-line" />;
}

export function MenuLabel({ children }: { children: React.ReactNode }) {
  return <DM.Label className="label-mono px-2.5 pb-1 pt-2 text-ink-3">{children}</DM.Label>;
}

// ------------------------------------------------------------------ Switch
export function Switch({
  checked,
  onCheckedChange,
  disabled,
  id,
  label,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  disabled?: boolean;
  id?: string;
  label?: string;
}) {
  return (
    <Sw.Root
      id={id}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className="relative h-6 w-11 shrink-0 rounded-full border border-line-strong bg-sunken transition-colors data-[state=checked]:border-primary data-[state=checked]:bg-primary disabled:opacity-50"
    >
      <Sw.Thumb className="block h-[18px] w-[18px] translate-x-[2px] rounded-full bg-elevated shadow-sm transition-transform duration-200 data-[state=checked]:translate-x-[22px] data-[state=checked]:bg-on-primary" />
    </Sw.Root>
  );
}

// ------------------------------------------------------------------ Tabs
export const Tabs = T.Root;
export const TabsContent = T.Content;

export function TabsList({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <T.List className={cn("scrollbar-none flex gap-6 overflow-x-auto border-b border-line", className)}>{children}</T.List>
  );
}

export function TabsTrigger({ value, children, count }: { value: string; children: React.ReactNode; count?: number | null }) {
  return (
    <T.Trigger
      value={value}
      className="group relative -mb-px shrink-0 whitespace-nowrap border-b-2 border-transparent px-0.5 pb-3 pt-1 text-[15px] text-ink-3 transition-colors hover:text-ink data-[state=active]:border-ink data-[state=active]:text-ink dark:data-[state=active]:border-amber"
    >
      {children}
      {count !== undefined && count !== null && <span className="ml-1.5 text-ink-3">({count})</span>}
    </T.Trigger>
  );
}

// ------------------------------------------------------------------ Tooltip
export function Tooltip({ content, children, side = "top" }: { content: React.ReactNode; children: React.ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <Tt.Provider delayDuration={250}>
      <Tt.Root>
        <Tt.Trigger asChild>{children}</Tt.Trigger>
        <Tt.Portal>
          <Tt.Content
            side={side}
            sideOffset={6}
            className="z-50 max-w-xs rounded-[3px] bg-inverse px-2.5 py-1.5 text-xs text-ink-inverse shadow-float data-[state=delayed-open]:animate-[menu-in_120ms_ease-out]"
          >
            {content}
          </Tt.Content>
        </Tt.Portal>
      </Tt.Root>
    </Tt.Provider>
  );
}
