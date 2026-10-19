import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Column } from './DataTable';
import { DataTable } from './DataTable';

interface Row {
  id: string;
  name: string;
  width: number | null;
}

const ROWS: Row[] = [
  { id: 'a', name: 'Charlie', width: 5 },
  { id: 'b', name: 'Alpha', width: 2.5 },
  { id: 'c', name: 'Bravo', width: null },
  { id: 'd', name: 'Delta', width: 1 },
];

const COLUMNS: Column<Row>[] = [
  { key: 'name', header: 'Name', sortValue: (r) => r.name, cell: (r) => r.name },
  {
    key: 'width',
    header: 'Width',
    align: 'right',
    sortValue: (r) => r.width,
    cell: (r) => r.width ?? '–',
  },
  { key: 'note', header: 'Note', cell: () => 'n/a' },
];

const names = () =>
  within(screen.getAllByRole('rowgroup')[1] as HTMLElement)
    .getAllByRole('row')
    .map((row) => within(row).getAllByRole('cell')[0]?.textContent);

function header(name: string) {
  return screen.getByRole('columnheader', { name: new RegExp(`^${name}`) });
}

describe('DataTable', () => {
  it('keeps the incoming order until a column is sorted', () => {
    render(<DataTable caption="Rows" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(names()).toEqual(['Charlie', 'Alpha', 'Bravo', 'Delta']);
    expect(header('Name')).toHaveAttribute('aria-sort', 'none');
  });

  it('sorts ascending then descending and announces it with aria-sort', async () => {
    const user = userEvent.setup();
    render(<DataTable caption="Rows" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);

    await user.click(screen.getByRole('button', { name: /Width/ }));
    expect(header('Width')).toHaveAttribute('aria-sort', 'ascending');
    expect(header('Name')).toHaveAttribute('aria-sort', 'none');
    // Null sorts last either way.
    expect(names()).toEqual(['Delta', 'Alpha', 'Charlie', 'Bravo']);

    await user.click(screen.getByRole('button', { name: /Width/ }));
    expect(header('Width')).toHaveAttribute('aria-sort', 'descending');
    expect(names()).toEqual(['Charlie', 'Alpha', 'Delta', 'Bravo']);

    await user.click(screen.getByRole('button', { name: /Name/ }));
    expect(header('Name')).toHaveAttribute('aria-sort', 'ascending');
    expect(header('Width')).toHaveAttribute('aria-sort', 'none');
    expect(names()).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']);
  });

  it('does not offer sorting on a column without a sort value', () => {
    render(<DataTable caption="Rows" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(header('Note')).not.toHaveAttribute('aria-sort');
    expect(screen.queryByRole('button', { name: /Note/ })).toBeNull();
  });

  it('applies a default sort', () => {
    render(
      <DataTable
        caption="Rows"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        defaultSort={{ key: 'name', direction: 'descending' }}
      />,
    );
    expect(header('Name')).toHaveAttribute('aria-sort', 'descending');
    expect(names()).toEqual(['Delta', 'Charlie', 'Bravo', 'Alpha']);
  });

  it('paginates 50 rows per page', async () => {
    const user = userEvent.setup();
    const many: Row[] = Array.from({ length: 120 }, (_, i) => ({
      id: String(i),
      name: `Row ${String(i).padStart(3, '0')}`,
      width: i,
    }));
    render(<DataTable caption="Rows" columns={COLUMNS} rows={many} rowKey={(r) => r.id} />);
    expect(names()).toHaveLength(50);
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument();
    expect(names()[0]).toBe('Row 050');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(names()).toHaveLength(20);
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('selects a row by click and by keyboard, and marks the selected row', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DataTable
        caption="Rows"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        selectedKey="b"
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByRole('row', { name: /Delta/ }));
    expect(onSelect).toHaveBeenLastCalledWith(ROWS[3]);
    screen.getByRole('row', { name: /Bravo/ }).focus();
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenLastCalledWith(ROWS[2]);
    expect(screen.getByRole('row', { name: /Alpha/ })).toHaveAttribute('aria-selected', 'true');
  });

  it('jumps to the page of a newly selected row', () => {
    const many: Row[] = Array.from({ length: 120 }, (_, i) => ({
      id: String(i),
      name: `Row ${String(i).padStart(3, '0')}`,
      width: i,
    }));
    const { rerender } = render(
      <DataTable
        caption="Rows"
        columns={COLUMNS}
        rows={many}
        rowKey={(r) => r.id}
        selectedKey={null}
      />,
    );
    rerender(
      <DataTable
        caption="Rows"
        columns={COLUMNS}
        rows={many}
        rowKey={(r) => r.id}
        selectedKey="110"
      />,
    );
    expect(screen.getByText('Page 3 of 3')).toBeInTheDocument();
  });
});
