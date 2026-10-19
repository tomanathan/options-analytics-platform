import { useEffect, useId, useRef, useState } from 'react';

interface MultiSelectProps {
  label: string;
  options: readonly string[];
  selected: readonly string[];
  onChange: (selected: string[]) => void;
  /** Shown when nothing is selected. */
  emptyLabel: string;
  /** Selections beyond this are refused (for example three highlighted underlyings). */
  max?: number;
}

/** A button that opens a checkbox list. Closes on Escape or an outside click. */
export function MultiSelect({
  label,
  options,
  selected,
  onChange,
  emptyLabel,
  max,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const toggle = (option: string) => {
    if (selected.includes(option)) {
      onChange(selected.filter((item) => item !== option));
    } else if (max === undefined || selected.length < max) {
      onChange([...selected, option]);
    }
  };

  const summary =
    selected.length === 0
      ? emptyLabel
      : selected.length <= 3
        ? selected.join(', ')
        : `${selected.length} selected`;

  return (
    <div className="field" ref={root}>
      <span className="field__label">{label}</span>
      <div className="multiselect">
        <button
          type="button"
          className="control multiselect__button"
          aria-haspopup="true"
          aria-expanded={open}
          aria-controls={panelId}
          aria-label={`${label}: ${summary}`}
          onClick={() => setOpen((value) => !value)}
        >
          {summary}
          <span aria-hidden="true" className="multiselect__caret">
            {'▾'}
          </span>
        </button>
        {open && (
          <div className="multiselect__panel" id={panelId} role="group" aria-label={label}>
            {options.map((option) => {
              const checked = selected.includes(option);
              const blocked = !checked && max !== undefined && selected.length >= max;
              return (
                <label key={option} className="multiselect__option">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={blocked}
                    onChange={() => toggle(option)}
                  />
                  <span>{option}</span>
                </label>
              );
            })}
            {max !== undefined && <p className="multiselect__hint">Choose up to {max}.</p>}
          </div>
        )}
      </div>
    </div>
  );
}
