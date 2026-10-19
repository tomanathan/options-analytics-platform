import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Speed } from './Scrubber';
import { Scrubber } from './Scrubber';

const DATES = ['2026-09-24', '2026-09-25', '2026-09-28'];

function setup(overrides: Partial<Parameters<typeof Scrubber>[0]> = {}) {
  const handlers = {
    onSeek: vi.fn(),
    onToggle: vi.fn(),
    onStep: vi.fn(),
    onSpeed: vi.fn(),
    onStride: vi.fn(),
  };
  render(
    <Scrubber
      dates={DATES}
      index={1}
      playing={false}
      speed={1 as Speed}
      maxSpeed={4}
      stride="every"
      {...handlers}
      {...overrides}
    />,
  );
  return { user: userEvent.setup(), ...handlers };
}

describe('Scrubber', () => {
  it('exposes the date through aria-valuetext and shows it', () => {
    setup();
    const range = screen.getByRole('slider', { name: 'Session date' });
    expect(range).toHaveAttribute('aria-valuetext', 'Sep 25, 2026');
    expect(range).toHaveAttribute('min', '0');
    expect(range).toHaveAttribute('max', '2');
    expect(screen.getByText('2026-09-25')).toBeInTheDocument();
  });

  it('toggles playback with Space on the slider, once per press', async () => {
    const { user, onToggle } = setup();
    screen.getByRole('slider').focus();
    await user.keyboard(' ');
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('steps with the arrow keys', async () => {
    const { user, onStep } = setup();
    screen.getByRole('slider').focus();
    await user.keyboard('{ArrowRight}');
    expect(onStep).toHaveBeenLastCalledWith(1);
    await user.keyboard('{ArrowLeft}');
    expect(onStep).toHaveBeenLastCalledWith(-1);
    expect(onStep).toHaveBeenCalledTimes(2);
  });

  it('does not double-fire Space on the play button', async () => {
    const { user, onToggle } = setup();
    screen.getByRole('button', { name: 'Play' }).focus();
    await user.keyboard(' ');
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('labels the play button by state and reports it as pressed', () => {
    setup({ playing: true });
    expect(screen.getByRole('button', { name: 'Pause' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('calls the play button Replay when the last session is on screen', () => {
    setup({ atEnd: true });
    expect(screen.getByRole('button', { name: 'Replay' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Play' })).toBeNull();
  });

  it('keeps the transport apart from Speed and Stride', () => {
    setup();
    const transport = document.querySelector('.scrubber__transport') as HTMLElement;
    const options = document.querySelector('.scrubber__options') as HTMLElement;
    expect(within(transport).getByRole('button', { name: 'Play' })).toBeInTheDocument();
    expect(within(transport).getByRole('button', { name: 'Previous session' })).toBeInTheDocument();
    expect(within(transport).getByRole('button', { name: 'Next session' })).toBeInTheDocument();
    expect(within(transport).getByRole('slider', { name: 'Session date' })).toBeInTheDocument();
    expect(within(transport).queryByRole('radiogroup', { name: 'Speed' })).toBeNull();
    expect(within(transport).queryByRole('radiogroup', { name: 'Stride' })).toBeNull();
    expect(within(options).getByRole('radiogroup', { name: 'Speed' })).toBeInTheDocument();
    expect(within(options).getByRole('radiogroup', { name: 'Stride' })).toBeInTheDocument();
  });

  it('steps with the buttons', async () => {
    const { user, onStep } = setup();
    await user.click(screen.getByRole('button', { name: 'Next session' }));
    await user.click(screen.getByRole('button', { name: 'Previous session' }));
    expect(onStep.mock.calls).toEqual([[1], [-1]]);
  });

  it('seeks when the slider moves', () => {
    const { onSeek } = setup();
    const range = screen.getByRole('slider') as HTMLInputElement;
    // Controlled range: drive the native setter so React sees a change event.
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    setter?.call(range, '2');
    range.dispatchEvent(new Event('input', { bubbles: true }));
    expect(onSeek).toHaveBeenCalledWith(2);
  });

  it('caps the speed when motion is reduced', async () => {
    const { user, onSpeed } = setup({ maxSpeed: 1 });
    expect(screen.getByRole('radio', { name: '2×' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: '4×' })).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: '4×' }));
    expect(onSpeed).not.toHaveBeenCalled();
  });

  it('changes speed and stride', async () => {
    const { user, onSpeed, onStride } = setup();
    await user.click(screen.getByRole('radio', { name: '2×' }));
    expect(onSpeed).toHaveBeenCalledWith(2);
    await user.click(screen.getByRole('radio', { name: 'Monthly' }));
    expect(onStride).toHaveBeenCalledWith('monthly');
  });
});
