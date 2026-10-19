import { useEffect, useMemo, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';

export type SortDirection = 'ascending' | 'descending';

export interface Column<T> {
  key: string;
  header: string;
  align?: 'left' | 'right';
  /** Provide to make the column sortable; null sorts last in either direction. */
  sortValue?: (row: T) => number | string | null;
  cell: (row: T) => ReactNode;
  title?: string;
}

interface DataTableProps<T> {
  caption: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  pageSize?: number;
  /** Initial sort; null keeps the order the rows arrive in. */
  defaultSort?: { key: string; direction: SortDirection } | null;
  selectedKey?: string | null;
  onSelect?: (row: T) => void;
}

function compare(a: number | string | null, b: number | string | null, direction: SortDirection) {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const result =
    typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b));
  return direction === 'ascending' ? result : -result;
}

/** A sortable, paginated table. Sort state is announced with `aria-sort`. */
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  pageSize = 50,
  defaultSort = null,
  selectedKey = null,
  onSelect,
}: DataTableProps<T>) {
  const [sort, setSort] = useState(defaultSort);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((item) => item.key === sort.key);
    const value = column?.sortValue;
    if (!value) return rows;
    return [...rows].sort((a, b) => compare(value(a), value(b), sort.direction));
  }, [rows, columns, sort]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, pageCount - 1);
  const visible = sorted.slice(current * pageSize, (current + 1) * pageSize);

  useEffect(() => {
    setPage(0);
  }, [rows]);

  useEffect(() => {
    if (selectedKey === null) return;
    const index = sorted.findIndex((row) => rowKey(row) === selectedKey);
    if (index >= 0) setPage(Math.floor(index / pageSize));
    // Jump only when the selection changes, not when the user sorts or pages.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey]);

  const toggleSort = (key: string) => {
    setPage(0);
    setSort((previous) =>
      previous?.key === key
        ? { key, direction: previous.direction === 'ascending' ? 'descending' : 'ascending' }
        : { key, direction: 'ascending' },
    );
  };

  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect?.(row);
    }
  };

  const first = sorted.length === 0 ? 0 : current * pageSize + 1;
  const last = Math.min(sorted.length, (current + 1) * pageSize);

  return (
    <div className="table-wrap">
      <div className="table-scroll">
        <table className="table">
          <caption className="visually-hidden">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => {
                const sortable = column.sortValue !== undefined;
                const active = sort?.key === column.key ? sort.direction : undefined;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={column.align === 'right' ? 'is-num' : undefined}
                    aria-sort={sortable ? (active ?? 'none') : undefined}
                    title={column.title}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        className="table__sort"
                        onClick={() => toggleSort(column.key)}
                      >
                        {column.header}
                        <span aria-hidden="true" className="table__arrow">
                          {active === 'ascending' ? '▲' : active === 'descending' ? '▼' : ''}
                        </span>
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const key = rowKey(row);
              const selected = key === selectedKey;
              return (
                <tr
                  key={key}
                  className={selected ? 'is-selected' : undefined}
                  aria-selected={onSelect ? selected : undefined}
                  tabIndex={onSelect ? 0 : undefined}
                  onClick={onSelect ? () => onSelect(row) : undefined}
                  onKeyDown={onSelect ? (event) => onRowKeyDown(event, row) : undefined}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={column.align === 'right' ? 'is-num' : undefined}
                    >
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="table__pager">
        <span aria-live="polite">
          {first}
          {'–'}
          {last} of {sorted.length}
        </span>
        <div className="table__pager-buttons">
          <button
            type="button"
            className="button"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            Previous
          </button>
          <span>
            Page {current + 1} of {pageCount}
          </span>
          <button
            type="button"
            className="button"
            disabled={current >= pageCount - 1}
            onClick={() => setPage(current + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
