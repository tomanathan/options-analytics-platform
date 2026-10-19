import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Measured } from './Measured';

describe('Measured', () => {
  it('reserves minHeight before the width is known, then renders the child at the width', async () => {
    render(<Measured minHeight={340}>{(width) => <p>chart {width}</p>}</Measured>);
    // The test observer reports 800 px, but only after the 50 ms debounce.
    const placeholder = screen.getByTestId('measured-placeholder');
    expect(placeholder).toHaveStyle({ height: '340px' });
    expect(screen.queryByText(/chart/)).toBeNull();

    expect(await screen.findByText('chart 800')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId('measured-placeholder')).toBeNull());
  });

  it('reserves nothing when no minHeight is given', () => {
    render(<Measured>{() => <p>chart</p>}</Measured>);
    expect(screen.getByTestId('measured-placeholder')).toHaveStyle({ height: '0px' });
  });
});
