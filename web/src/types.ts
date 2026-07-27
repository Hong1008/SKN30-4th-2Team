export type Screen =
  | 'upload-and-type'
  | 'out-of-scope'
  | 'processing'
  | 'results'
  | 'clause-detail'
  | 'chatbot'

export type BadgeStatus = 'matched' | 'modified' | 'review' | 'missing'

export interface ClauseResult {
  id: string
  article: string
  excerpt: string
  status: BadgeStatus
  category: string
  summary: string
  toxic_patterns?: string[]
}

export interface MissingClauseResult {
  id: string
  category: string
  title: string
  text: string
  explanation: string
}

// --- API Types based on api-draft.md ---

export interface ApiResponse<T> {
  data: T;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface ApiError {
  code: string;
  message: string;
  field: string | null;
  retryable: boolean;
  next_action: string;
  details: any;
}

export interface ReviewSessionData {
  session_id: string;
  review_state: string;
  upload?: {
    file_name: string;
    size_bytes: number;
    extension: string;
  };
  scope_status: string;
  scope_message: string;
  suggested_contract_type: string | null;
  selected_contract_type: string | null;
  selection_source: string | null;
  candidates: any[];
  matched_clause_count: number;
  allowed_actions: string[];
  expires_at: string;
  can_start_review?: boolean;
}

export interface ReviewProgress {
  sequence: number;
  stage: string;
  current: number;
  total: number;
  percent: number;
  message: string;
}

export interface ReviewData {
  review_id: string;
  review_state: string;
  mcp_review_status: string | null;
  snapshot?: any;
  progress: ReviewProgress;
  error?: ApiError | null;
  started_at?: string;
  completed_at?: string;
  expires_at?: string;
  links?: any;
}

export interface ResultsData {
  review: {
    review_id: string;
    review_state: string;
    mcp_review_status: string;
    contract_type: string;
    started_at: string;
    completed_at: string;
    expires_at: string;
    disclaimer: string;
  };
  summary: {
    clause_results: {
      total: number;
      NONE: number;
      EXTRA: number;
      NO_MATCH: number;
    };
    missing_standard_clauses: number;
    toxic_pattern_candidates: number;
  };
  clause_results: any[];
  missing_standard_clauses: any[];
}
