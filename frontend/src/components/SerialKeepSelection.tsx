import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getApiErrorMessage } from '../api/client';
import { fetchAvailableSerials } from '../features/serials/api';
import { serialQueryKeys } from '../features/serials/queryKeys';

type SerialKeepSelectionProps = {
  productId: number;
  selected: string[];
  onChange: (serials: string[]) => void;
  disabled: boolean;
};

export default function SerialKeepSelection({ productId, selected, onChange, disabled }: SerialKeepSelectionProps) {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);

  useEffect(() => {
    const timer = setTimeout(() => { setDebouncedSearch(search.trim()); setPage(1); }, 250);
    return () => clearTimeout(timer);
  }, [search]);

  const serialsQuery = useQuery({
    queryKey: serialQueryKeys.available(productId, debouncedSearch, page),
    queryFn: () => fetchAvailableSerials({ productId, search: debouncedSearch, page }),
  });

  return (
    <div className="stack">
      <div className="field">
        <label htmlFor="serial-keep-search">Search serials to keep</label>
        <input
          id="serial-keep-search"
          className="input"
          type="search"
          value={search}
          disabled={disabled}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Last digits of an IMEI"
        />
      </div>
      {serialsQuery.isLoading ? <p className="muted-text">Loading serials…</p> : null}
      {serialsQuery.error ? (
        <p className="field-warning" role="alert">{getApiErrorMessage(serialsQuery.error, 'Unable to load serials.')}</p>
      ) : null}
      {!serialsQuery.isLoading && !serialsQuery.error && serialsQuery.data?.items.length === 0 ? (
        <p className="muted-text">No matching in-stock serials.</p>
      ) : null}
      <ul className="serial-picker__list" aria-label="Serials to keep">
        {serialsQuery.data?.items.map((serial) => (
          <li key={serial.id}>
            <label className={`serial-picker__row serial-backfill__choice${selected.includes(serial.serial_number) ? ' is-picked' : ''}`}>
              <input
                type="checkbox"
                checked={selected.includes(serial.serial_number)}
                disabled={disabled}
                onChange={(event) => onChange(event.target.checked
                  ? [...selected, serial.serial_number]
                  : selected.filter((entry) => entry !== serial.serial_number))}
              />
              <span className="serial-picker__number">{serial.serial_number}</span>
            </label>
          </li>
        ))}
      </ul>
      {(serialsQuery.data?.total_pages ?? 1) > 1 ? (
        <div className="serial-picker__pages">
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={disabled || page <= 1}
            onClick={() => setPage((current) => current - 1)}
          >Previous</button>
          <span className="muted-text">Page {page} of {serialsQuery.data?.total_pages}</span>
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={disabled || page >= (serialsQuery.data?.total_pages ?? 1)}
            onClick={() => setPage((current) => current + 1)}
          >Next</button>
        </div>
      ) : null}
      {selected.length > 0 ? (
        <div>
          <p className="muted-text">Selected across all pages and searches:</p>
          <ul className="serial-chips__list" aria-label="Selected serials">
            {selected.map((serial) => (
              <li key={serial} className="serial-chip">
                <span className="serial-chip__value">{serial}</span>
                <button
                  type="button"
                  className="serial-chip__remove"
                  aria-label={`Remove serial ${serial}`}
                  disabled={disabled}
                  onClick={() => onChange(selected.filter((entry) => entry !== serial))}
                >×</button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
