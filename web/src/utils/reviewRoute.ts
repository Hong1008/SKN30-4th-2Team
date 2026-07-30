export function getReviewIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/review\/([^/]+)\/(?:progress|results)(?:\/|$)/)
  if (!match || match[1] === 'new') return null
  try {
    return decodeURIComponent(match[1])
  } catch {
    return null
  }
}
