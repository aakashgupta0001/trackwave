import { useEffect, useState } from 'react'
import { ApiError } from './api'

export type FetchState<T> = {
  data: T | undefined
  loading: boolean
  error: string | undefined
}

/** Runs `fetcher` whenever `deps` changes; ignores results from stale/superseded calls. */
export function useFetch<T>(fetcher: () => Promise<T>, deps: unknown[]): FetchState<T> {
  const [data, setData] = useState<T | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(undefined)

    fetcher()
      .then((result) => {
        if (cancelled) return
        setData(result)
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Could not reach the backend.')
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, loading, error }
}
