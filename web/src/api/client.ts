export class ApiError extends Error {
  public code: string;
  public status: number;
  public details?: any;

  constructor(status: number, data: any) {
    super(data.message || `API Error: ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = data.code || 'UNKNOWN_ERROR';
    this.details = data.details;
  }
}

export const client = async <T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> => {
  const url = `/api/v1${endpoint}`;
  
  const headers = new Headers(options.headers || {});
  if (!options.body || typeof options.body === 'string') {
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
  });

  let data;
  try {
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      data = await response.json();
    } else {
      data = await response.text();
    }
  } catch (err) {
    data = { message: 'Failed to parse response' };
  }

  if (!response.ok) {
    throw new ApiError(response.status, data);
  }

  return data as T;
};
