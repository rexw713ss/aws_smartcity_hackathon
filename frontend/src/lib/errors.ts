import { ContractError, HttpError } from './copilot'
import { translate, type Language } from './i18n'

/** Localize application errors while retaining source diagnostics when present. */
export function formatError(cause: unknown, language: Language): string {
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) =>
    translate(language, key, values)
  // Preserve existing English diagnostics, including precise contract failures.
  if (language === 'en' && cause instanceof Error) return cause.message
  if (cause instanceof ContractError) return t('errorContract')
  if (cause instanceof HttpError) {
    const message = cause.status === 429 ? t('errorBusy')
      : [401, 403].includes(cause.status) ? t('errorAccess')
        : cause.status === 404 ? t('errorEndpoint')
          : t('errorRequest', { status: cause.status })
    return cause.detail ? `${message} ${t('errorDetail', { detail: cause.detail })}` : message
  }
  if (cause instanceof TypeError && /fetch|network|load failed/i.test(cause.message)) return t('errorNetwork')
  if (cause instanceof Error && cause.name === 'AbortError') return t('timeout')
  return cause instanceof Error
    ? `${t('unexpected')} ${t('errorDetail', { detail: cause.message })}`
    : t('unexpected')
}
