import { useEffect, useId, useRef, useState } from 'react';

interface NumberFieldProps {
  label: string;
  value: number | null;
  /** Called on blur or Enter with the parsed number, or null when the box is empty. */
  onCommit: (value: number | null) => void;
  placeholder?: string;
  step?: number;
  min?: number;
}

/** A numeric input that commits on blur or Enter, so typing does not fire a request per key. */
export function NumberField({
  label,
  value,
  onCommit,
  placeholder,
  step = 0.5,
  min = 0,
}: NumberFieldProps) {
  const id = useId();
  const [text, setText] = useState(value === null ? '' : String(value));
  useEffect(() => {
    setText(value === null ? '' : String(value));
  }, [value]);

  const commit = () => {
    const trimmed = text.trim();
    if (trimmed === '') {
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed) && parsed !== value) onCommit(parsed);
    else setText(value === null ? '' : String(value));
  };

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="control control--number"
        type="number"
        inputMode="decimal"
        value={text}
        min={min}
        step={step}
        placeholder={placeholder}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') commit();
        }}
      />
    </div>
  );
}

interface SliderFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onCommit: (value: number) => void;
}

const SLIDER_DEBOUNCE_MS = 250;

/** A slider that updates its readout immediately and commits after the pointer settles. */
export function SliderField({ label, value, min, max, step, format, onCommit }: SliderFieldProps) {
  const id = useId();
  const [local, setLocal] = useState(value);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    setLocal(value);
  }, [value]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label} <span className="field__value">{format(local)}</span>
      </label>
      <input
        id={id}
        className="slider"
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        aria-valuetext={format(local)}
        onChange={(event) => {
          const next = Number(event.target.value);
          setLocal(next);
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => onCommit(next), SLIDER_DEBOUNCE_MS);
        }}
      />
    </div>
  );
}

interface SwitchFieldProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function SwitchField({ label, checked, onChange }: SwitchFieldProps) {
  return (
    <label className="switch">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="switch__track" aria-hidden="true" />
      <span>{label}</span>
    </label>
  );
}
