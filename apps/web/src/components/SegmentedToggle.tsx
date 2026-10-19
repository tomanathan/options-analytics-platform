import { useId } from 'react';

export interface ToggleOption<T extends string | number> {
  value: T;
  label: string;
  disabled?: boolean;
}

interface SegmentedToggleProps<T extends string | number> {
  label: string;
  value: T;
  options: readonly ToggleOption<T>[];
  onChange: (value: T) => void;
}

/** A radio-group styled as joined buttons. Used for map, view, layout, axis, speed and stride. */
export function SegmentedToggle<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: SegmentedToggleProps<T>) {
  const labelId = useId();
  return (
    <div className="field">
      <span className="field__label" id={labelId}>
        {label}
      </span>
      <div className="segmented" role="radiogroup" aria-labelledby={labelId}>
        {options.map((option) => {
          const checked = option.value === value;
          return (
            <button
              key={String(option.value)}
              type="button"
              role="radio"
              aria-checked={checked}
              disabled={option.disabled}
              className={checked ? 'segmented__item is-active' : 'segmented__item'}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
